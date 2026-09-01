/* VoltMax panel — AJAX qatlami va skroll xotirasi.
 *
 * Ikki vazifa:
 *   1. Har bir tugma/havola sahifani to'liq qayta yuklamasdan ishlaydi;
 *   2. Ekrandagi joy eslab qolinadi — AJAX amalidan keyin ham, F5 bosilganda
 *      ham, orqaga qaytilganda ham foydalanuvchi o'sha joyda qoladi.
 *
 * JS o'chirilgan bo'lsa panel odatdagidek (to'liq yuklanish bilan) ishlayveradi.
 */
(function () {
  'use strict';

  /* JS ishlayotganining belgisi: brauzerning o'z kalendar tugmasi shunda
     yashiriladi. JS yuklanmasa u joyida qoladi va sana baribir tanlanadi. */
  document.documentElement.classList.add('js');

  var STORE_KEY = 'voltmax_scroll_v2';
  var MAX_ENTRIES = 30;

  function layout() { return document.querySelector('.layout'); }
  function pathKey() { return location.pathname + location.search; }

  /* ══ Skroll xotirasi ═══════════════════════════════════════
     Har sahifa uchun alohida yozuv saqlanadi (bitta umumiy kalit emas) —
     shunda A sahifadan B ga o'tib, orqaga qaytilganda ham joy tiklanadi. */

  function readStore() {
    try { return JSON.parse(sessionStorage.getItem(STORE_KEY)) || {}; }
    catch (e) { return {}; }
  }

  function writeStore(store) {
    try {
      // Xotira cheksiz o'smasin — eng eski yozuvlar chiqarib tashlanadi
      var keys = Object.keys(store);
      if (keys.length > MAX_ENTRIES) {
        keys.sort(function (a, b) { return store[a].at - store[b].at; })
            .slice(0, keys.length - MAX_ENTRIES)
            .forEach(function (k) { delete store[k]; });
      }
      sessionStorage.setItem(STORE_KEY, JSON.stringify(store));
    } catch (e) { /* private rejim yoki to'lgan xotira — e'tiborsiz */ }
  }

  var saveTimer = null;
  function saveScroll(immediate) {
    // `beforeunload`ga tayanmaymiz: u mobil brauzerlarda va bfcache'da
    // har doim ham ishlamaydi. Lekin har kadrda yozish ham ortiqcha —
    // skroll paytida sekundiga ~60 marta JSON yozilardi. Shu sabab throttle.
    function commit() {
      saveTimer = null;
      var store = readStore();
      store[pathKey()] = { y: window.scrollY, at: Date.now() };
      writeStore(store);
    }
    if (immediate) {
      if (saveTimer) { clearTimeout(saveTimer); }
      commit();
      return;
    }
    if (saveTimer) return;
    saveTimer = setTimeout(commit, 150);
  }

  function savedY() {
    var entry = readStore()[pathKey()];
    return entry ? entry.y : 0;
  }

  /* Tarkib to'liq joylashgunicha (shrift/rasm yuklanishi) balandlik o'zgaradi,
     shuning uchun tiklashni bir necha kadr davomida takrorlaymiz. */
  function restoreScroll(y) {
    var target = typeof y === 'number' ? y : savedY();
    if (!target) {
      // Aniq 0 berilgan bo'lsa — bu "yangi sahifa, tepadan boshla" degani.
      // Busiz oldingi sahifaning skroll joyi saqlanib qolardi.
      if (y === 0) window.scrollTo(0, 0);
      return;
    }
    var tries = 0;
    (function attempt() {
      window.scrollTo(0, target);
      if (++tries < 8 && Math.abs(window.scrollY - target) > 2) {
        requestAnimationFrame(attempt);
      }
    })();
  }

  if ('scrollRestoration' in history) {
    // Brauzerning o'z tiklashi almashtirilgan tarkib bilan to'g'ri ishlamaydi
    history.scrollRestoration = 'manual';
  }

  // Diqqat: to'g'ridan-to'g'ri `saveScroll` berilsa, hodisa obyekti `immediate`
  // argumenti sifatida kelib qoladi va throttle ishlamay qolardi.
  window.addEventListener('scroll', function () { saveScroll(); }, { passive: true });
  window.addEventListener('beforeunload', function () { saveScroll(true); });
  window.addEventListener('pageshow', function () { restoreScroll(); });
  document.addEventListener('DOMContentLoaded', function () { restoreScroll(); });
  window.addEventListener('load', function () { restoreScroll(); });

  /* ══ Yuqoridagi yuklanish chizig'i ═════════════════════════ */
  var bar;
  function progress(on) {
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'ajax-bar';
      document.body.appendChild(bar);
    }
    bar.classList.toggle('active', on);
  }

  /* ══ Tarkibni almashtirish ════════════════════════════════ */
  function swap(html, url, keepY) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var fresh = doc.querySelector('.layout');

    // Kutilmagan javob (masalan sessiya tugab, login sahifasiga otkazildi)
    if (!fresh || !layout()) { window.location.href = url; return; }

    layout().innerHTML = fresh.innerHTML;
    document.title = doc.title;

    if (url && url.split('#')[0] !== location.href.split('#')[0]) {
      history.pushState({}, '', url);
    }
    restoreScroll(typeof keepY === 'number' ? keepY : 0);
    saveScroll();
    armToasts();   // almashgan tarkibdagi yangi xabarlar
    syncToggleFields();
    // Sahifa xarita bilan bo'lsa — uni qayta ishga tushiramiz
    if (window.initStationMap) window.initStationMap();
  }

  /* ══ Qisman almashtirish ══════════════════════════════════
     Butun `.layout` emas, FAQAT belgilangan bo'lakni yangilaydi.
     Qidiruv maydoni almashuvdan tashqarida qolgani uchun fokus ham,
     kursor ham joyida turadi — sahifa "sakramaydi". */
  /* Filtr qatorining o'zi almashadigan hududdan TASHQARIDA turadi (fokus va
     kursor joyida qolishi uchun). Lekin unda serverga bog'liq qismlar bor:
     «Filtr» tugmasidagi son, qo'llanilgan filtr belgisi, tozalash tugmasi.
     Ular yangilanmasa qatorda eski holat qolib ketardi — masalan filtr
     olib tashlangach ham tugma qizil turaverardi.

     `data-live-sync` qo'yilgan har bir bo'lak yangi javobdan qayta olinadi. */
  function syncLiveChrome(doc) {
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-live-sync]'), function (box) {
        // Foydalanuvchi shu bo'lak ichida ishlayotgan bo'lsa tegilmaydi:
        // almashtirish ochiq ro'yxatni yopib, fokusni yo'qotardi
        if (box.contains && document.activeElement
            && box.contains(document.activeElement)) return;

        var id = box.getAttribute('id');
        var fresh = id && doc.getElementById ? doc.getElementById(id) : null;
        if (fresh) box.innerHTML = fresh.innerHTML;
      });
  }

  function partialSwap(html, url, selector) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var fresh = doc.querySelector(selector);
    var current = document.querySelector(selector);

    // Kutilmagan javob (masalan sessiya tugab, login sahifasiga o'tkazildi)
    if (!fresh || !current) { window.location.href = url; return false; }

    current.innerHTML = fresh.innerHTML;
    syncLiveChrome(doc);
    if (doc.title) document.title = doc.title;
    if (url && url.split('#')[0] !== location.href.split('#')[0]) {
      history.pushState({}, '', url);
    }
    // Almashgan bo'lakdagi katakchalar yangi — panel holatini tiklaymiz
    refreshBulkBar();
    return true;
  }

  function setBusy(el, busy) {
    if (!el) return;
    el.classList.toggle('is-busy', busy);
    // `disabled` qo'ymaymiz: nomli tugmalar FormData'dan tushib qolmasin
    el.setAttribute('aria-busy', busy ? 'true' : 'false');
  }

  /* ══ Formalar (barcha POST amallari) ══════════════════════ */
  document.addEventListener('submit', function (e) {
    // Inline `onsubmit="return confirm(...)"` bekor qilgan bo'lsa to'xtaymiz —
    // busiz "Bekor qilish" bosilganda ham so'rov ketib qolardi.
    if (e.defaultPrevented) return;

    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute('data-no-ajax')) return;
    if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;

    e.preventDefault();

    var action = form.getAttribute('action') || location.href;
    var button = form.querySelector('button[type=submit], button:not([type])');
    var y = window.scrollY;

    setBusy(button, true);
    progress(true);

    fetch(action, {
      method: 'POST',
      body: new FormData(form),
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      redirect: 'follow',
    })
      .then(function (res) {
        return res.text().then(function (html) {
          // Amal shu sahifada bajarilgan bo'lsa — joyida qolamiz
          var samePage = res.url.split('#')[0] === location.href.split('#')[0];
          swap(html, res.url, samePage ? y : 0);
        });
      })
      .catch(function () { window.location.href = action; })
      .then(function () { setBusy(button, false); progress(false); });
  });

  /* ══ Ichki havolalar (filtr, sahifalash, navigatsiya) ═════ */
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;

    var link = e.target.closest && e.target.closest('a');
    if (!link) return;
    if (link.hasAttribute('data-no-ajax') || link.target || link.hasAttribute('download')) return;
    // Jonli filtr havolalari butun sahifani emas, faqat jadvalni yangilaydi —
    // ular quyidagi alohida ishlovchida qayta ishlanadi
    if (link.hasAttribute('data-live-filter')) return;

    var href = link.getAttribute('href');
    if (!href || href.charAt(0) === '#' || /^[a-z][a-z0-9+.-]*:/i.test(href)) return;
    if (link.origin && link.origin !== location.origin) return;

    e.preventDefault();
    saveScroll(true);      // joriy sahifa joyini darhol eslab qolamiz (orqaga qaytish uchun)
    progress(true);

    fetch(link.href, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    })
      .then(function (res) {
        return res.text().then(function (html) {
          var samePath = res.url.split('?')[0] === location.href.split('?')[0];
          // Bir sahifa ichidagi filtr/sahifalash — joyida qolamiz,
          // boshqa bo'limga o'tish — yuqoridan boshlanadi.
          swap(html, res.url, samePath ? window.scrollY : 0);
        });
      })
      .catch(function () { window.location.href = link.href; })
      .then(function () { progress(false); });
  });

  /* ══ Orqaga / oldinga ═════════════════════════════════════ */
  window.addEventListener('popstate', function () {
    var y = savedY();
    progress(true);
    fetch(location.href, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    })
      .then(function (res) { return res.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var fresh = doc.querySelector('.layout');
        if (!fresh || !layout()) { location.reload(); return; }
        layout().innerHTML = fresh.innerHTML;
        document.title = doc.title;
        restoreScroll(y);
      })
      .catch(function () { location.reload(); })
      .then(function () { progress(false); });
  });





  /* ══ Pul maydonlari ═══════════════════════════════════════
     Yozayotganda raqamlar 3 xonadan ajratiladi: 1500 -> 1 500
     Fokusdan chiqqanda kasr qismi to'ldiriladi: 1 500 -> 1 500.00
     Serverga ajratgichsiz toza son ketadi (widgets.py tozalaydi). */
  var MONEY_NBSP = ' ';

  function groupDigits(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, MONEY_NBSP);
  }

  /* Vergul ham, nuqta ham KASR AJRATGICHI: "1500,50" va "1500.50" bir xil
     o'qiladi. Ekranda doim nuqta ko'rsatiladi (123 000.00 standarti).
     Ming ajratgichlarini foydalanuvchi kiritmaydi — ular o'zi qo'yiladi. */
  function cleanMoney(raw) {
    // Birinchi vergul/nuqta — kasr boshlanishi; keyingilari e'tiborsiz
    var normalized = raw.replace(/,/g, '.');
    var firstDot = normalized.indexOf('.');

    var wholeSource = firstDot === -1 ? normalized : normalized.slice(0, firstDot);
    var fractionSource = firstDot === -1 ? null : normalized.slice(firstDot + 1);

    var whole = wholeSource.replace(/\D/g, '').replace(/^0+(?=\d)/, '');
    var fraction = fractionSource === null
      ? null
      : fractionSource.replace(/\D/g, '').slice(0, 2);

    return { whole: whole, fraction: fraction };
  }

  function formatWhileTyping(raw) {
    var parsed = cleanMoney(raw);
    if (!parsed.whole && parsed.fraction === null) return '';
    var out = groupDigits(parsed.whole || '0');
    // Nuqta kiritilgan bo'lsa, kasr hali bo'sh bo'lsa ham ko'rsatiladi —
    // aks holda foydalanuvchi nuqta qo'yishi bilan u yo'qolib ketardi.
    if (parsed.fraction !== null) out += '.' + parsed.fraction;
    return out;
  }

  /* Fokusdan chiqqanda — jadval va kartalardagi ko'rinish bilan bir xil */
  function formatFinal(raw) {
    var parsed = cleanMoney(raw);
    if (!parsed.whole && !parsed.fraction) return '';
    var amount = parseFloat((parsed.whole || '0') + '.' + (parsed.fraction || '0'));
    if (isNaN(amount)) return '';
    var fixed = amount.toFixed(2).split('.');
    return groupDigits(fixed[0]) + '.' + fixed[1];
  }

  /* Fokus olganda "1 500.00" dagi bo'sh kasr olib tashlanadi — tahrirlash
     qulay bo'lsin. Nolga teng bo'lmagan kasr ("1 500.50") saqlanadi. */
  function formatForEditing(raw) {
    return formatWhileTyping(raw.replace(/[.,]00\s*$/, ''));
  }

  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains('money-input')) return;
    el.value = formatForEditing(el.value);
  });

  /* Kursorni joyida ushlab qolish: formatlashdan keyin uning oldidagi
     RAQAMLAR soni o'zgarmasligi kerak, aks holda kursor oxiriga sakraydi. */
  function reformat(input, formatter) {
    var before = input.value.slice(0, input.selectionStart || 0);
    var digitsBefore = (before.match(/[\d.,]/g) || []).length;

    input.value = formatter(input.value);

    var pos = 0, seen = 0;
    while (pos < input.value.length && seen < digitsBefore) {
      if (/[\d.]/.test(input.value[pos])) seen++;
      pos++;
    }
    try { input.setSelectionRange(pos, pos); } catch (e) { /* ba'zi turlarda mumkin emas */ }
  }

  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains('money-input')) return;
    el.value = formatForEditing(el.value);
  });

  document.addEventListener('input', function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains('money-input')) return;
    reformat(el, formatWhileTyping);
  });

  document.addEventListener('blur', function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains('money-input')) return;
    el.value = formatFinal(el.value);
  }, true);   // blur ko'pikka chiqmaydi — capture bosqichida ushlaymiz

  /* ══ Shartli maydonlar ════════════════════════════════════
     `data-toggle-when="<checkbox nomi>"` bo'lgan blok faqat o'sha
     belgilash qutisi yoqilgandagina ko'rinadi. Server tomonda ham
     tekshiruv bor — bu faqat forma qisqaroq ko'rinishi uchun. */
  function syncToggleFields(scope) {
    var fields = (scope || document).querySelectorAll('[data-toggle-when]');
    Array.prototype.forEach.call(fields, function (field) {
      var name = field.getAttribute('data-toggle-when');
      var box = document.querySelector('input[type=checkbox][name="' + name + '"]');
      field.hidden = !(box && box.checked);
    });
  }

  document.addEventListener('change', function (e) {
    if (e.target && e.target.type === 'checkbox' && e.target.name) {
      syncToggleFields();
    }
  });

  document.addEventListener('DOMContentLoaded', function () { syncToggleFields(); });

  /* ══ Sidebar: yig'ish va mobil menyu ══════════════════════
     Holat <html> atributida turadi va localStorage'da saqlanadi —
     shunda sahifa ochilishida "sakrash" bo'lmaydi (base.html'dagi
     inline skript uni birinchi bo'yoqdan oldin qo'yadi). */
  var root = document.documentElement;

  var MOBILE = 900;
  function isMobile() { return window.innerWidth <= MOBILE; }

  function setSidebar(state) {
    root.setAttribute('data-sidebar', state);
    try { localStorage.setItem('voltmax_sidebar', state); } catch (e) { /* e'tiborsiz */ }
    syncMenuLabel();
  }

  /* Gamburger yozuvi holatga mos bo'lsin — desktopda "yig'ish/yoyish",
     mobil ekranda "menyu". */
  function syncMenuLabel() {
    var btn = document.getElementById('nav-open');
    if (!btn) return;
    var label = isMobile()
      ? 'Menyu'
      : (root.getAttribute('data-sidebar') === 'collapsed' ? 'Menyuni yoyish' : "Menyuni yig'ish");
    btn.setAttribute('title', label);
    btn.setAttribute('aria-label', label);
  }

  function setNav(open) {
    root.setAttribute('data-nav', open ? 'open' : 'closed');
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest) return;

    // Yagona gamburger: desktopda sidebarni yig'adi/yoyadi,
    // mobil ekranda chetdan chiqadigan menyuni ochadi/yopadi.
    if (e.target.closest('#nav-open')) {
      if (isMobile()) {
        setNav(root.getAttribute('data-nav') !== 'open');
      } else {
        setSidebar(root.getAttribute('data-sidebar') === 'collapsed' ? 'expanded' : 'collapsed');
      }
      return;
    }

    // Fon yoki menyu elementi bosilganda mobil menyu yopiladi
    if (e.target.closest('#sidebar-scrim') || e.target.closest('.sidebar nav a')) {
      setNav(false);
    }
  });

  // Esc — mobil menyuni yopadi
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') setNav(false);
  });

  // Yig'ilgan sidebar keng ekranga qaytganda menyu ochiq qolib ketmasin
  window.addEventListener('resize', function () {
    if (!isMobile()) setNav(false);
    syncMenuLabel();
  });

  /* ══ Xabarlar (toast) ═════════════════════════════════════
     Yopish tugmasi delegatsiya orqali ishlaydi — tarkib AJAX bilan
     almashganda ham qayta bog'lash shart emas. */
  var AUTO_HIDE_MS = 5000;

  function hideToast(toast) {
    if (!toast || toast.classList.contains('hiding')) return;
    toast.classList.add('hiding');
    setTimeout(function () {
      var stack = toast.parentNode;
      if (toast.parentNode) toast.parentNode.removeChild(toast);
      // Bo'shab qolgan konteyner bosishlarni to'sib qolmasin
      if (stack && !stack.children.length && stack.parentNode) {
        stack.parentNode.removeChild(stack);
      }
    }, 200);
  }

  document.addEventListener('click', function (e) {
    var close = e.target.closest && e.target.closest('.toast-close');
    if (!close) return;
    e.preventDefault();
    hideToast(close.closest('.toast'));
  });

  /* Muvaffaqiyat xabarlari o'zi so'nadi; xatolar esa foydalanuvchi
     yopmaguncha turadi — ular e'tibor talab qiladi. */
  function armToasts() {
    var toasts = document.querySelectorAll('.toast:not([data-armed])');
    Array.prototype.forEach.call(toasts, function (toast) {
      toast.setAttribute('data-armed', '1');
      if (toast.classList.contains('error')) return;

      var timer = setTimeout(function () { hideToast(toast); }, AUTO_HIDE_MS);
      // Sichqoncha ustida turganda o'chib ketmasin — o'qib ulgurish uchun
      toast.addEventListener('mouseenter', function () { clearTimeout(timer); });
      toast.addEventListener('mouseleave', function () {
        timer = setTimeout(function () { hideToast(toast); }, 2000);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    armToasts();
    syncMenuLabel();
  });


  /* ══ Rasm yuklash maydoni ═════════════════════════════════
     Barcha ishlov delegatsiya orqali — maydon AJAX bilan sahifaga
     qo'yilganda ham qayta bog'lash shart emas.

     Server tarafi Django'ning `<name>-clear` mexanizmi bo'yicha ishlaydi:
     o'chirish tugmasi yashirin maydonni "1" qiladi, xolos. */
  var MAX_IMAGE_MB = 5;

  function idParts(box) {
    return {
      file: box.querySelector('.id-input'),
      clear: box.querySelector('[data-clear-flag]'),
      preview: box.querySelector('[data-preview]'),
      name: box.querySelector('[data-file-name]'),
      undo: box.querySelector('[data-undo]'),
    };
  }

  function idSay(box, text, isError) {
    var el = idParts(box).name;
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('is-error', !!isError);
  }

  /* Boshlang'ich holatga qaytaradi: saqlangan rasm bo'lsa — o'sha,
     bo'lmasa — bo'sh maydon. */
  function idReset(box) {
    var p = idParts(box);
    var src = box.getAttribute('data-initial-src');
    if (p.file) p.file.value = '';
    if (p.clear) p.clear.value = '';
    if (p.preview) p.preview.setAttribute('src', src || '');
    box.classList.toggle('has-image', !!src);
    idSay(box, box.getAttribute('data-initial-name') || '');
    if (p.undo) p.undo.hidden = true;
  }

  function idShowFile(box, file) {
    var p = idParts(box);

    if (!file.type || file.type.indexOf('image/') !== 0) {
      idSay(box, 'Faqat rasm fayllari qabul qilinadi', true);
      if (p.file) p.file.value = '';
      return;
    }
    if (file.size > MAX_IMAGE_MB * 1024 * 1024) {
      idSay(box, 'Rasm ' + MAX_IMAGE_MB + ' MB dan katta — kichikroq fayl tanlang', true);
      if (p.file) p.file.value = '';
      return;
    }

    // Yangi fayl tanlandi -> o'chirish belgisi bekor qilinadi, aks holda
    // server ikkalasini birga olib "contradiction" xatosini berardi.
    if (p.clear) p.clear.value = '';
    box.classList.add('has-image');
    idSay(box, file.name);
    if (p.undo) p.undo.hidden = false;

    if (p.preview && window.FileReader) {
      var reader = new FileReader();
      reader.onload = function (ev) { p.preview.setAttribute('src', ev.target.result); };
      reader.readAsDataURL(file);
    }
  }

  document.addEventListener('change', function (e) {
    var box = e.target.closest && e.target.closest('[data-image-drop]');
    if (!box || !e.target.classList.contains('id-input')) return;
    var file = e.target.files && e.target.files[0];
    if (file) idShowFile(box, file);
    else idReset(box);
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest) return;
    var box = e.target.closest('[data-image-drop]');
    if (!box) return;
    var p = idParts(box);

    if (e.target.closest('[data-pick]')) {
      e.preventDefault();
      if (p.file) p.file.click();
      return;
    }
    if (e.target.closest('[data-remove]')) {
      e.preventDefault();
      if (p.file) p.file.value = '';
      if (p.clear) p.clear.value = '1';
      if (p.preview) p.preview.setAttribute('src', '');
      box.classList.remove('has-image');
      idSay(box, "O'chiriladi — saqlashni bosing");
      // Saqlangan rasm bo'lgandagina qaytarish ma'noga ega
      if (p.undo) p.undo.hidden = !box.getAttribute('data-initial-src');
      return;
    }
    if (e.target.closest('[data-undo]')) {
      e.preventDefault();
      idReset(box);
    }
  });

  /* Sudrab tashlash. `dragover`da preventDefault bo'lmasa brauzer faylni
     yangi oynada ochib yuboradi. */
  document.addEventListener('dragover', function (e) {
    var box = e.target.closest && e.target.closest('[data-image-drop]');
    if (!box) return;
    e.preventDefault();
    box.classList.add('is-drag');
  });

  document.addEventListener('dragleave', function (e) {
    var box = e.target.closest && e.target.closest('[data-image-drop]');
    // Ichki elementga o'tishda ham `dragleave` keladi — chegarani tekshiramiz
    if (box && !box.contains(e.relatedTarget)) box.classList.remove('is-drag');
  });

  document.addEventListener('drop', function (e) {
    var box = e.target.closest && e.target.closest('[data-image-drop]');
    if (!box) return;
    e.preventDefault();
    box.classList.remove('is-drag');

    var files = e.dataTransfer && e.dataTransfer.files;
    if (!files || !files.length) return;

    var p = idParts(box);
    // Inputga ham yozamiz — formaga aynan shu fayl ketishi kerak
    if (p.file && window.DataTransfer) {
      try {
        var dt = new DataTransfer();
        dt.items.add(files[0]);
        p.file.files = dt.files;
      } catch (err) { /* eski brauzer — quyida ogohlantiramiz */ }
    }
    if (p.file && p.file.files && p.file.files.length) idShowFile(box, p.file.files[0]);
    else idSay(box, "Brauzer sudrab tashlashni qo'llamaydi — tugma orqali tanlang", true);
  });

  /* ══ Xabar oluvchilar oynasi ══════════════════════════════
     Profilaktika jadvalida son ustunidagi raqam yoki "Xabar yuborish"
     bosilganda ochiladi. Ro'yxat serverdan olinadi (`data-url`), shuning
     uchun har bir qatorga yashirin ro'yxat qo'yish shart emas.

     `data-notify` berilgan bo'lsa — oyna ichida yuborish formasi ham
     ko'rinadi: operator avval KIMGA ketishini ko'radi, keyin bosadi.
     Shu sabab bu amalda confirm() ishlatilmaydi. */

  var lastFocused = null;

  function modal() { return document.getElementById('recipients-modal'); }

  /* ══ Modal oynalar (umumiy) ═══════════════════════════════
     `data-modal-open="#id"` — ochadi, `data-modal-close` — yopadi.
     Yopilgach fokus oynani ochgan tugmaga qaytadi, aks holda klaviatura
     bilan ishlayotgan foydalanuvchi sahifa boshiga tushib qolardi. */
  function openModal(box, opener) {
    if (!box) return;
    box.hidden = false;
    lastFocused = opener || null;

    // Birinchi kiritish maydoniga fokus — oyna ochilishi bilan yozish mumkin
    var first = box.querySelector('input:not([type=hidden]), select, textarea');
    if (first && first.focus) first.focus();
  }

  function closeModal(box) {
    box = box || modal();
    if (!box || box.hidden) return;
    box.hidden = true;
    if (lastFocused && lastFocused.focus) lastFocused.focus();
    lastFocused = null;
  }

  document.addEventListener('click', function (e) {
    var opener = e.target.closest && e.target.closest('[data-modal-open]');
    if (!opener) return;
    e.preventDefault();
    openModal(document.querySelector(opener.getAttribute('data-modal-open')), opener);
  });

  function renderRecipients(data) {
    var box = modal();
    if (!box) return;

    var sub = box.querySelector('[data-modal-sub]');
    var body = box.querySelector('[data-modal-body]');
    var list = data.recipients || [];

    if (sub) sub.textContent = data.station + ' · ' + data.target;

    if (!list.length) {
      body.innerHTML = '<div class="recipient-empty">Bu stansiyada xabar oluvchi yo\'q</div>';
      return;
    }

    var wrap = document.createElement('div');
    wrap.className = 'recipient-list';
    list.forEach(function (person) {
      var row = document.createElement('div');
      row.className = 'recipient-row';

      var name = document.createElement('span');
      name.className = 'r-name';
      // textContent — ism foydalanuvchi kiritgan matn, HTML sifatida
      // qo'yilmasligi kerak
      name.textContent = person.name;

      var why = document.createElement('span');
      why.className = 'r-why';
      why.textContent = person.reason;

      row.appendChild(name);
      row.appendChild(why);
      wrap.appendChild(row);
    });

    body.innerHTML = '';
    body.appendChild(wrap);
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest) return;

    var closer = e.target.closest('[data-modal-close]');
    if (closer) {
      e.preventDefault();
      closeModal(closer.closest('.modal'));
      return;
    }

    var trigger = e.target.closest('[data-recipients]');
    if (!trigger) return;
    e.preventDefault();

    var box = modal();
    if (!box) return;

    lastFocused = trigger;
    var body = box.querySelector('[data-modal-body]');
    var form = box.querySelector('[data-modal-form]');
    var notify = trigger.getAttribute('data-notify');

    // Yuborish formasi faqat xabar yuborish mumkin bo'lgan qatorda ko'rinadi
    if (form) {
      form.hidden = !notify;
      if (notify) form.setAttribute('action', notify);
    }

    body.innerHTML = '<div class="recipient-empty">Yuklanmoqda…</div>';
    box.hidden = false;

    var closeBtn = box.querySelector('.modal-close');
    if (closeBtn) closeBtn.focus();

    fetch(trigger.getAttribute('data-url'), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    })
      .then(function (res) { return res.json(); })
      .then(renderRecipients)
      .catch(function () {
        body.innerHTML = '<div class="recipient-empty">Ro\'yxatni yuklab bo\'lmadi</div>';
      });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    Array.prototype.forEach.call(document.querySelectorAll('.modal:not([hidden])'),
                                 function (box) { closeModal(box); });
  });

  /* ══ Ommaviy tanlash ══════════════════════════════════════
     Jadvaldagi katakchalar belgilanganda ustki panel paydo bo'ladi va
     belgilanganlar soni ko'rsatiladi. Delegatsiya orqali — sahifa AJAX
     bilan almashganda ham ishlayveradi. */

  function bulkItems() {
    return Array.prototype.slice.call(document.querySelectorAll('[data-check-item]'));
  }

  function refreshBulkBar() {
    var bar = document.querySelector('[data-bulk-bar]');
    if (!bar) return;

    var items = bulkItems();
    var checked = items.filter(function (box) { return box.checked; });

    bar.hidden = checked.length === 0;
    var counter = bar.querySelector('[data-bulk-count]');
    if (counter) counter.textContent = String(checked.length);

    // "Hammasi" katakchasi uch holatda bo'ladi: bo'sh, qisman, to'liq
    var all = document.querySelector('[data-check-all]');
    if (all) {
      all.checked = items.length > 0 && checked.length === items.length;
      all.indeterminate = checked.length > 0 && checked.length < items.length;
    }
  }

  document.addEventListener('change', function (e) {
    if (!e.target.matches) return;

    if (e.target.matches('[data-check-all]')) {
      bulkItems().forEach(function (box) { box.checked = e.target.checked; });
      refreshBulkBar();
      return;
    }
    if (e.target.matches('[data-check-item]')) refreshBulkBar();
  });

  document.addEventListener('DOMContentLoaded', refreshBulkBar);

  /* ══ Katta harfli maydonlar ════════════════════════════════
     RFID karta raqami qurilmadan har doim katta harfda keladi. CSS
     `text-transform` faqat KO'RINISHNI o'zgartiradi — serverga kichik
     harf ketaverardi. Bu yerda qiymatning o'zi o'giriladi, kursor esa
     o'z joyida qoladi. */
  /* Fayl tanlangach forma o'zi yuboriladi.

     Avatar uchun alohida «Saqlash» tugmasi ortiqcha qadam bo'lardi:
     rasm tanlangan payt niyat allaqachon aniq. Tugmasiz forma esa
     jimgina turib qolardi — foydalanuvchi rasm tanlab, hech narsa
     bo'lmaganini ko'rardi. */
  document.addEventListener('change', function (e) {
    var input = e.target;
    if (!input.matches || !input.matches('[data-autosubmit]')) return;
    if (input.files && input.files.length === 0) return;

    var form = input.form || input.closest('form');
    if (form) form.submit();
  });

  document.addEventListener('input', function (e) {
    var field = e.target;
    if (!field.matches || !field.matches('[data-uppercase]')) return;

    var upper = field.value.toUpperCase();
    if (upper === field.value) return;

    var start = field.selectionStart;
    var end = field.selectionEnd;
    field.value = upper;
    // Uzunlik o'zgarmagani uchun kursorni o'z joyiga qaytarish xavfsiz
    try { field.setSelectionRange(start, end); } catch (err) { /* e'tiborsiz */ }
  });

  /* ══ Jonli filtr ══════════════════════════════════════════
     Qidiruv maydoniga yozilganda va filtr tabi bosilganda FAQAT jadval
     yangilanadi — sahifa qayta yuklanmaydi va joyidan siljimaydi.

     So'rov baribir SERVERGA ketadi: jadval sahifalangan, shuning uchun
     ko'rinib turgan qatorlarni yashirish noto'g'ri natija berardi —
     foydalanuvchi butun bazani qidiryapman deb o'ylardi. */
  var LIVE_DELAY = 300;
  var liveTimer = null;
  var liveController = null;
  var liveLast = null;

  function liveTarget(el) {
    return el.getAttribute('data-target') || '[data-live-region]';
  }

  function liveUrl(form) {
    var params = new URLSearchParams();
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.disabled || el.type === 'submit') return;

      // Katakchalar bir nomda bir nechta bo'lishi mumkin (korporativ filtr) —
      // `set` ularni bir-birini bosib ketardi, shuning uchun `append`
      if (el.type === 'checkbox' || el.type === 'radio') {
        if (el.checked) params.append(el.name, el.value);
        return;
      }
      if (el.value !== '') params.set(el.name, el.value);   // bo'sh qiymat manzilni ifloslantirmasin
    });
    var query = params.toString();
    return (form.getAttribute('action') || location.pathname) + (query ? '?' + query : '');
  }

  function liveFetch(url, selector, form) {
    if (url === liveLast) return;
    liveLast = url;

    // Oldingi so'rov hali kelmagan bo'lsa bekor qilamiz: sekinroq javob
    // keyinroq kelib, yangi natijani bosib ketardi
    if (liveController) liveController.abort();
    liveController = typeof AbortController === 'function' ? new AbortController() : null;

    if (form) form.classList.add('is-searching');
    progress(true);

    return fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      signal: liveController ? liveController.signal : undefined,
    })
      .then(function (res) {
        return res.text().then(function (html) { partialSwap(html, url, selector); });
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;   // yangisi bilan almashtirildi
        window.location.href = url;
      })
      .then(function () {
        progress(false);
        if (form) form.classList.remove('is-searching');
      });
  }

  document.addEventListener('input', function (e) {
    var form = e.target.closest && e.target.closest('[data-live-search]');
    if (!form || e.target.type !== 'search') return;

    clearTimeout(liveTimer);
    liveTimer = setTimeout(function () {
      liveFetch(liveUrl(form), liveTarget(form), form);
    }, LIVE_DELAY);
  });

  /* Enter bosilsa kutmasdan darhol qidiramiz (va sahifa qayta yuklanmaydi) */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-live-search')) return;
    e.preventDefault();
    clearTimeout(liveTimer);

    // Kengaytirilgan filtr oynasi shu formaning ichida bo'lishi mumkin —
    // "Qo'llash" bosilgach u yopiladi, aks holda natija oyna ostida qolardi
    Array.prototype.forEach.call(form.querySelectorAll('.modal'), function (box) {
      if (!box.hidden) closeModal(box);
    });

    liveFetch(liveUrl(form), liveTarget(form), form);
  });

  /* Filtr tabi — u ham faqat jadvalni yangilaydi. Aktiv holat almashuvdan
     tashqarida qolgani uchun uni shu yerda qo'lda ko'chiramiz. */
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;

    var tab = e.target.closest && e.target.closest('[data-live-filter]');
    if (!tab) return;
    e.preventDefault();

    var group = tab.closest('.filter-tabs');
    if (group) {
      Array.prototype.forEach.call(group.querySelectorAll('a'), function (a) {
        a.classList.toggle('active', a === tab);
      });
    }

    // Tanlangan filtr qidiruv formasiga yoziladi va so'rov SHU FORMA
    // bo'yicha quriladi — shunda qidiruv, korporativ tanlov va tab birga
    // ketadi. Tab havolasidan foydalanilsa boshqa filtrlar yo'qolardi.
    //
    // Maydon nomi sahifaga qarab o'zgaradi: kartalarda `status`, amallar
    // jurnalida `action`. Ilgari u qattiq yozilgan edi va jurnaldagi
    // tablar hech narsa qilmasdi — qiymat mavjud bo'lmagan maydonga
    // yozilardi.
    var field = tab.getAttribute('data-filter-field') || 'status';
    var value = tab.getAttribute('data-filter-value') || '';
    var form = document.querySelector('[data-live-search]');
    var hidden = form && form.querySelector('input[name=' + field + ']');
    if (hidden) hidden.value = value;

    if (form) liveFetch(liveUrl(form), liveTarget(form), null);
    else liveFetch(tab.href, liveTarget(tab), null);
  });

  /* ══ Ko'p tanlovli filtr ══════════════════════════════════
     Katakchali ochiluvchi ro'yxat. Tanlov o'zgarganda jadval darhol
     yangilanadi — "Qo'llash" tugmasini qidirish shart emas. */
  function msClose(box) {
    if (!box) return;
    box.classList.remove('is-open');
    var panel = box.querySelector('[data-ms-panel]');
    var toggle = box.querySelector('[data-ms-toggle]');
    if (panel) panel.hidden = true;
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
  }

  function msSync(box) {
    var items = box.querySelectorAll('[data-ms-item]');
    var chosen = 0;
    Array.prototype.forEach.call(items, function (i) { if (i.checked) chosen += 1; });

    var counter = box.querySelector('[data-ms-count]');
    if (counter) {
      counter.textContent = String(chosen);
      counter.hidden = chosen === 0;
    }
    box.classList.toggle('has-value', chosen > 0);
  }

  function msApply(box) {
    msSync(box);
    var form = box.closest('[data-live-search]');
    if (form) liveFetch(liveUrl(form), liveTarget(form), null);
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest) return;
    var box = e.target.closest('[data-multi-select]');

    // Tashqariga bosilsa ochiq ro'yxat yopiladi
    if (!box) {
      Array.prototype.forEach.call(
        document.querySelectorAll('[data-multi-select].is-open'), msClose);
      return;
    }

    if (e.target.closest('[data-ms-toggle]')) {
      e.preventDefault();
      var open = !box.classList.contains('is-open');
      Array.prototype.forEach.call(
        document.querySelectorAll('[data-multi-select].is-open'), msClose);
      if (open) {
        box.classList.add('is-open');
        var panel = box.querySelector('[data-ms-panel]');
        var toggle = box.querySelector('[data-ms-toggle]');
        if (panel) panel.hidden = false;
        if (toggle) toggle.setAttribute('aria-expanded', 'true');
      }
      return;
    }

    if (e.target.closest('[data-ms-close]')) { e.preventDefault(); msClose(box); return; }

    if (e.target.closest('[data-ms-clear]')) {
      e.preventDefault();
      Array.prototype.forEach.call(box.querySelectorAll('[data-ms-item]'), function (i) {
        i.checked = false;
      });
      msApply(box);
    }
  });

  document.addEventListener('change', function (e) {
    if (!e.target.matches || !e.target.matches('[data-ms-item]')) return;
    var box = e.target.closest('[data-multi-select]');
    if (box) msApply(box);
  });

  /* Esc — ochiq ro'yxatni yopadi */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-multi-select].is-open'), msClose);
  });

  /* ══ Telefon maydoni ══════════════════════════════════════
     Raqam yozilgani sari `+998 (90) 123-45-67` ko'rinishiga keladi.
     Server baribir kanonik holga keltiradi (`PhoneInput`), lekin operator
     yozayotganda raqamni o'qiy olishi kerak — 12 ta raqam ketma-ket
     yozilganda xatoni ko'rish qiyin.

     Faqat raqamlar hisobga olinadi: qavs, chiziqcha va bo'shliqni maydon
     o'zi qo'yadi, foydalanuvchi ularni yozishi shart emas. */
  var PHONE_CODE = '998';

  function phoneDigits(value) {
    var digits = (value || '').replace(/\D/g, '');

    // Mamlakat kodi maydonda doim turadi — uni ikki marta yozib
    // yuborilganini ham to'g'rilaymiz
    if (digits.indexOf(PHONE_CODE) === 0) digits = digits.slice(PHONE_CODE.length);
    // Eski yozuv: 8 90 ... — birinchi 8 tashlanadi
    else if (digits.length === 10 && digits.charAt(0) === '8') digits = digits.slice(1);

    return digits.slice(0, 9);      // O'zbekiston raqami — 9 xonali
  }

  function phoneFormat(value) {
    var d = phoneDigits(value);
    if (!d) return '';

    var out = '+' + PHONE_CODE + ' (' + d.slice(0, 2);
    if (d.length < 2) return out;              // "+998 (9"
    out += ')';
    if (d.length > 2) out += ' ' + d.slice(2, 5);
    if (d.length > 5) out += '-' + d.slice(5, 7);
    if (d.length > 7) out += '-' + d.slice(7, 9);
    return out;
  }

  function phoneApply(input) {
    var before = input.value;
    var atEnd = input.selectionStart === before.length;
    var formatted = phoneFormat(before);
    if (formatted === before) return;

    input.value = formatted;
    // Kursor oxirida bo'lsa o'sha yerda qoladi; o'rtada tahrirlanayotgan
    // bo'lsa uni qo'zg'atmaymiz — sakrab ketgani yozishni buzardi
    if (atEnd && input.setSelectionRange) {
      input.setSelectionRange(formatted.length, formatted.length);
    }
  }

  document.addEventListener('input', function (e) {
    if (e.target.matches && e.target.matches('.phone-input')) phoneApply(e.target);
  });

  /* Bo'sh maydon bosilganda kod o'zi paydo bo'ladi: operator "+998" ni
     har safar yozib o'tirmaydi */
  document.addEventListener('focusin', function (e) {
    if (!e.target.matches || !e.target.matches('.phone-input')) return;
    if (!e.target.value) {
      e.target.value = '+' + PHONE_CODE + ' (';
      if (e.target.setSelectionRange) {
        var end = e.target.value.length;
        e.target.setSelectionRange(end, end);
      }
    }
  });

  /* Faqat kod qolgan bo'lsa maydon bo'shatiladi — aks holda "raqam
     kiritilgan" bo'lib ko'rinardi va forma uni saqlashga urinardi */
  document.addEventListener('focusout', function (e) {
    if (!e.target.matches || !e.target.matches('.phone-input')) return;
    if (!phoneDigits(e.target.value)) e.target.value = '';
  });


  /* ══ Xavfli sozlamalar ════════════════════════════════════
     Ba'zi tugmachalar butun tizimga ta'sir qiladi: texnik ishlar rejimi
     mobil ilovadagi hamma foydalanuvchiga ogohlantirish chiqaradi, qat'iy
     RFID rejimi esa tasdiqlanmagan kartalarni darhol to'xtatadi.

     Tasodifan bosilgani darrov bilinmaydi, shuning uchun YOQISHDAN oldin
     so'raladi. O'chirish so'ralmaydi — u holatni xavfsiz tomonga qaytaradi. */
  document.addEventListener('change', function (e) {
    var input = e.target;
    if (!input.matches || !input.matches('input[type=checkbox][data-confirm]')) return;
    if (!input.checked) return;

    if (!window.confirm(input.getAttribute('data-confirm'))) {
      input.checked = false;
    }
  });

  /* ══ Raqamli rekvizitlar: hisob raqami va STIR ════════════
     20 ta (yoki 9 ta) raqam ketma-ket yozilsa xato ko'rinmaydi — bitta
     raqam tushib qolgani ham, ortiqchasi ham bilinmaydi. Maydon ularni
     bo'laklarga ajratib turadi:

        hisob raqami  20208 000 5 00123612 001
        STIR          305 123 456

     Serverga baribir faqat raqamlar boradi (`BankAccountInput`, `InnInput`). */
  var DIGIT_MASKS = [
    { selector: '.account-input', groups: [5, 3, 1, 8, 3] },
    { selector: '.inn-input', groups: [3, 3, 3] },
  ];

  function groupByMask(value, groups) {
    var limit = groups.reduce(function (sum, size) { return sum + size; }, 0);
    var digits = (value || '').replace(/\D/g, '').slice(0, limit);
    if (!digits) return '';

    var parts = [];
    var start = 0;
    for (var i = 0; i < groups.length; i++) {
      var chunk = digits.slice(start, start + groups[i]);
      if (!chunk) break;
      parts.push(chunk);
      start += groups[i];
    }
    return parts.join(' ');
  }

  document.addEventListener('input', function (e) {
    var input = e.target;
    if (!input.matches) return;

    for (var i = 0; i < DIGIT_MASKS.length; i++) {
      if (!input.matches(DIGIT_MASKS[i].selector)) continue;

      var atEnd = input.selectionStart === input.value.length;
      var formatted = groupByMask(input.value, DIGIT_MASKS[i].groups);
      if (formatted === input.value) return;

      input.value = formatted;
      // Kursor oxirida bo'lsa o'sha yerda qoladi; o'rtada tahrirlanayotgan
      // bo'lsa uni qo'zg'atmaymiz — sakrab ketgani yozishni buzardi
      if (atEnd && input.setSelectionRange) {
        input.setSelectionRange(formatted.length, formatted.length);
      }
      return;
    }
  });

  /* ══ Sana tanlagich ═══════════════════════════════════════
     Brauzerning o'z kalendari har bir brauzerda boshqacha ko'rinadi va
     panel mavzusiga (ayniqsa qorong'isiga) mos kelmaydi. Shuning uchun
     `input[type=date]` maydonlariga o'z kalendarimiz ochiladi.

     Maydonning O'ZI o'zgarmaydi — qiymat baribir `YYYY-MM-DD` bo'lib
     qoladi va forma odatdagidek yuboriladi. JS o'chirilgan bo'lsa
     brauzerning o'z kalendari ishlayveradi. */
  var MONTHS = ['Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun',
                'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr'];
  /* Hafta dushanbadan boshlanadi */
  var WEEKDAYS = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya'];

  var dpPanel = null;     // yagona oyna — barcha maydonlar uchun qayta ishlatiladi
  var dpInput = null;     // hozir ochiq maydon
  var dpView = null;      // ko'rinib turgan oy (har doim oyning 1-kuni)

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function toISO(date) {
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
  }

  function parseISO(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!match) return null;
    var date = new Date(+match[1], +match[2] - 1, +match[3]);
    // 31-fevral kabi qiymatlar boshqa oyga sirg'alib ketadi — bunday
    // sanani "yo'q" deb hisoblaymiz, aks holda kalendar boshqa oyni ochardi
    return date.getMonth() === +match[2] - 1 ? date : null;
  }

  function startOfDay(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  /* Bayram kunlari serverdan olinadi: Google'ning ICS faylini brauzerdan
     to'g'ridan-to'g'ri o'qib bo'lmaydi (CORS), shuning uchun ma'lumot
     serverda yangilanadi va bazadan JSON bo'lib keladi.

     Nusxa brauzer xotirasida saqlanadi, lekin VERSIYA bilan: sahifa
     `<body data-holidays="...">` da oxirgi sinxronlash vaqtini beradi.
     Operator kalendarni yangilagach versiya o'zgaradi va eski nusxa
     o'z-o'zidan tashlanadi — aks holda "Google'dan yangilash" bosilsa ham
     kalendar eski ro'yxatni ko'rsatib turaverardi. */
  var HOLIDAY_KEY = 'voltmax_holidays';
  var dpHolidays = null;
  var dpHolidaysAsked = false;

  function dpHolidayVersion() {
    return (document.body && document.body.getAttribute('data-holidays')) || '0';
  }

  function dpReadHolidayCache() {
    try {
      var raw = sessionStorage.getItem(HOLIDAY_KEY);
      if (!raw) return null;
      var saved = JSON.parse(raw);
      // Versiya mos kelmasa nusxa eskirgan
      if (!saved || saved.v !== dpHolidayVersion()) return null;
      return saved.days || null;
    } catch (err) { return null; }
  }

  function dpLoadHolidays() {
    if (dpHolidays || dpHolidaysAsked) return;

    var cached = dpReadHolidayCache();
    if (cached) { dpHolidays = cached; return; }

    dpHolidaysAsked = true;
    fetch('/holidays.json', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        var days = (data && data.days) || {};
        dpHolidays = days;
        // Bo'sh natija saqlanmaydi: sinxronlash hali qilinmagan bo'lishi
        // mumkin, keyingi sahifada qayta so'ralsin
        if (Object.keys(days).length) {
          try {
            sessionStorage.setItem(HOLIDAY_KEY,
              JSON.stringify({ v: dpHolidayVersion(), days: days }));
          } catch (err) { /* xotira to'lgan bo'lsa e'tiborsiz */ }
        }
        // Oyna ochiq bo'lsa kunlar darhol belgilansin
        if (dpPanel && !dpPanel.hidden) dpRender();
      })
      .catch(function () {
        // Xato bo'lsa keyingi ochilishda qayta urinamiz
        dpHolidays = null;
        dpHolidaysAsked = false;
      });
  }

  function dpEl(tag, className, parent) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (parent) parent.appendChild(node);
    return node;
  }

  function dpNav(head, step, label, glyph) {
    var button = dpEl('button', 'dp-nav', head);
    button.type = 'button';
    button.setAttribute('data-dp-move', String(step));
    button.setAttribute('aria-label', label);
    button.textContent = glyph;
    return button;
  }

  function dpBuild() {
    /* Oyna `innerHTML` bilan emas, tugunlar orqali yig'iladi: shunda matn
       hech qachon HTML sifatida talqin qilinmaydi va tuzilma testda ham
       xuddi brauzerdagidek tekshiriladi. */
    var panel = dpEl('div', 'datepicker');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Sanani tanlash');
    panel.hidden = true;

    var head = dpEl('div', 'dp-head', panel);
    dpNav(head, -1, 'Oldingi oy', '‹');
    var title = dpEl('div', 'dp-title', head);
    title.setAttribute('data-dp-title', '');
    dpNav(head, 1, 'Keyingi oy', '›');

    var week = dpEl('div', 'dp-week', panel);
    WEEKDAYS.forEach(function (name) {
      dpEl('span', '', week).textContent = name;
    });

    var grid = dpEl('div', 'dp-grid', panel);
    grid.setAttribute('data-dp-grid', '');

    var legend = dpEl('div', 'dp-legend', panel);
    dpEl('span', 'dp-key is-holiday', legend).textContent = 'bayram';
    dpEl('span', 'dp-key is-weekend', legend).textContent = 'dam olish';

    var foot = dpEl('div', 'dp-foot', panel);
    var today = dpEl('button', 'link', foot);
    today.type = 'button';
    today.setAttribute('data-dp-today', '');
    today.textContent = 'Bugun';
    var clear = dpEl('button', 'link', foot);
    clear.type = 'button';
    clear.setAttribute('data-dp-clear', '');
    clear.textContent = 'Tozalash';

    document.body.appendChild(panel);
    return panel;
  }

  function dpLimits() {
    return {
      min: dpInput ? parseISO(dpInput.getAttribute('min')) : null,
      max: dpInput ? parseISO(dpInput.getAttribute('max')) : null
    };
  }

  function dpRender() {
    if (!dpPanel || !dpView) return;

    dpPanel.querySelector('[data-dp-title]').textContent =
      MONTHS[dpView.getMonth()] + ' ' + dpView.getFullYear();

    var grid = dpPanel.querySelector('[data-dp-grid]');
    while (grid.firstChild) grid.removeChild(grid.firstChild);

    var selected = dpInput ? parseISO(dpInput.value) : null;
    var today = startOfDay(new Date());
    var limits = dpLimits();

    // Dushanbadan boshlanadigan hafta: yakshanba (0) — 7-kun
    var weekday = dpView.getDay() || 7;
    var cursor = new Date(dpView.getFullYear(), dpView.getMonth(), 1 - (weekday - 1));

    /* Faqat SHU OYGA tegishli haftalar chiziladi — fevral 28 kun bo'lib
       dushanbadan boshlansa 4 qator, mart 31 kun bo'lib yakshanbadan
       boshlansa 6 qator. Doimiy 42 katakda oyning yarmi begona kunlar
       bilan to'lib, oyna keraksiz uzun bo'lardi. */
    var lastDay = new Date(dpView.getFullYear(), dpView.getMonth() + 1, 0).getDate();
    var weeks = Math.ceil((weekday - 1 + lastDay) / 7);

    for (var i = 0; i < weeks * 7; i++) {
      var day = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + i);
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'dp-day';
      button.textContent = day.getDate();
      button.setAttribute('data-dp-day', toISO(day));

      if (day.getMonth() !== dpView.getMonth()) button.classList.add('is-other');
      if (day.getTime() === today.getTime()) button.classList.add('is-today');

      // Shanba va yakshanba — dam olish kunlari
      var weekend = day.getDay() === 0 || day.getDay() === 6;
      if (weekend) button.classList.add('is-weekend');

      // Bayram: rangi bilan ham, sarlavhasi bilan ham ajralib turadi
      var iso = toISO(day);
      var holiday = dpHolidays ? dpHolidays[iso] : null;
      if (holiday) {
        button.classList.add('is-holiday');
        button.setAttribute('title', holiday);
      }
      if (selected && day.getTime() === selected.getTime()) {
        button.classList.add('is-selected');
        button.setAttribute('aria-current', 'date');
      }
      // Chegaradan tashqari sana bosilmaydi: forma baribir uni rad etardi
      if ((limits.min && day < limits.min) || (limits.max && day > limits.max)) {
        button.disabled = true;
      }
      grid.appendChild(button);
    }
  }

  function dpPlace() {
    if (!dpPanel || !dpInput) return;
    var box = dpInput.getBoundingClientRect();
    var height = dpPanel.offsetHeight || 320;
    var width = dpPanel.offsetWidth || 280;

    // Pastda joy bo'lmasa maydonning tepasida ochiladi
    var below = window.innerHeight - box.bottom;
    var top = below < height + 12 && box.top > height + 12
      ? box.top - height - 6
      : box.bottom + 6;

    var left = Math.min(box.left, window.innerWidth - width - 8);
    dpPanel.style.top = Math.max(8, top) + 'px';
    dpPanel.style.left = Math.max(8, left) + 'px';
  }

  function dpOpen(input) {
    if (!dpPanel) dpPanel = dpBuild();
    dpInput = input;
    var current = parseISO(input.value) || startOfDay(new Date());
    dpView = new Date(current.getFullYear(), current.getMonth(), 1);

    dpLoadHolidays();
    dpPanel.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    dpRender();
    dpPlace();
  }

  function dpClose() {
    if (!dpPanel || dpPanel.hidden) return;
    dpPanel.hidden = true;
    if (dpInput) dpInput.removeAttribute('aria-expanded');
    dpInput = null;
  }

  function dpPick(iso) {
    if (!dpInput) return;
    dpInput.value = iso;
    // `change` — boshqa qatlamlar (masalan jonli filtr) xabardor bo'lishi uchun
    dpInput.dispatchEvent(new Event('change', { bubbles: true }));
    dpClose();
  }

  function dpMove(step) {
    if (!dpView) return;
    dpView = new Date(dpView.getFullYear(), dpView.getMonth() + step, 1);
    dpRender();
  }

  function dpTarget(e) {
    return e.target && e.target.closest ? e.target : null;
  }

  document.addEventListener('mousedown', function (e) {
    var target = dpTarget(e);
    if (!target) return;

    var input = target.closest('input[type=date]');
    if (input && !input.hasAttribute('data-no-picker') && !input.disabled && !input.readOnly) {
      // Brauzerning o'z kalendari ochilmasligi kerak — ikkitasi birga chiqardi
      e.preventDefault();
      if (dpInput === input) { dpClose(); return; }
      input.focus();
      dpOpen(input);
      return;
    }
    if (dpPanel && !dpPanel.hidden && !target.closest('.datepicker')) dpClose();
  });

  document.addEventListener('click', function (e) {
    if (!dpPanel || dpPanel.hidden) return;
    var target = dpTarget(e);
    if (!target) return;

    var day = target.closest('[data-dp-day]');
    if (day) { e.preventDefault(); dpPick(day.getAttribute('data-dp-day')); return; }

    var move = target.closest('[data-dp-move]');
    if (move) { e.preventDefault(); dpMove(+move.getAttribute('data-dp-move')); return; }

    if (target.closest('[data-dp-today]')) { e.preventDefault(); dpPick(toISO(new Date())); return; }
    if (target.closest('[data-dp-clear]')) { e.preventDefault(); dpPick(''); }
  });

  document.addEventListener('keydown', function (e) {
    if (!dpPanel || dpPanel.hidden) return;
    if (e.key === 'Escape' || e.key === 'Tab') { dpClose(); return; }
    // Alt+o'q — oyni almashtirish (brauzer standarti bilan to'qnashmaydi)
    if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); dpMove(-1); }
    if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); dpMove(1); }
  });

  /* Sahifa siljiganda oyna maydondan ajralib qolmasligi kerak */
  window.addEventListener('scroll', function () {
    if (dpPanel && !dpPanel.hidden) dpPlace();
  }, true);
  window.addEventListener('resize', function () {
    if (dpPanel && !dpPanel.hidden) dpPlace();
  });

  /* ══ Mavzu almashtirish ═══════════════════════════════════
     Delegatsiya orqali — tugma tarkib almashganda ham ishlayveradi. */
  document.addEventListener('click', function (e) {
    var toggle = e.target.closest && e.target.closest('#theme-toggle');
    if (!toggle) return;
    var current = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('voltmax_theme', next); } catch (err) { /* e'tiborsiz */ }
  });

  /* ══ Yonga surilish sababini topish ══════════════════════════
     Sahifa yonga surilsa aybdor deyarli har doim BITTA element bo'ladi
     va uni ko'z bilan topib bo'lmaydi: u ekrandan tashqarida turadi.

     Manzilga `?overflow` qo'shilsa, har bir element o'lchanadi va
     hujjatdan kengroq chiqqanlari qizil ramka bilan belgilanadi hamda
     konsolga yoziladi.

     Ishlatish: sahifa manziliga `?overflow` qo'shing va konsolni oching.

     Bu FAQAT so'ralganda ishlaydi — har sahifada butun DOM ni o'lchash
     qimmatga tushardi. */
  if (window.location.search.indexOf('overflow') !== -1) {
    window.addEventListener('load', function () {
      var limit = document.documentElement.clientWidth;
      var guilty = [];

      document.querySelectorAll('*').forEach(function (el) {
        var box = el.getBoundingClientRect();
        // Chapga chiqib ketgani ham hisobga olinadi: u ham surilishga
        // sabab bo'ladi
        if (box.right > limit + 1 || box.left < -1) {
          guilty.push({
            element: el,
            selector: el.tagName.toLowerCase()
              + (el.id ? '#' + el.id : '')
              + (el.className && typeof el.className === 'string'
                 ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
            right: Math.round(box.right),
            width: Math.round(box.width),
          });
          el.style.outline = '2px solid #E5484D';
        }
      });

      // Natija SAHIFANING O'ZIDA ko'rsatiladi: konsolni ochib,
      // skrinshot qilish noqulay. Panel eng keng uchtasini yozadi —
      // odatda aybdor birinchisi bo'ladi, qolganlari uning ichidagi
      // elementlar.
      var panel = document.createElement('div');
      panel.setAttribute('data-overflow-report', '');
      panel.style.cssText = [
        'position:fixed', 'left:8px', 'bottom:8px', 'z-index:9999',
        'max-width:calc(100vw - 16px)', 'padding:12px 14px',
        'background:#111', 'color:#fff', 'font:12px/1.5 monospace',
        'border-radius:8px', 'box-shadow:0 8px 24px rgba(0,0,0,.4)',
        'white-space:pre-wrap', 'word-break:break-all',
      ].join(';');

      var doc = document.documentElement;
      var lines = [
        'Ko\'rinish: ' + limit + 'px · hujjat: ' + doc.scrollWidth + 'px'
        + ' · ortiqcha: ' + (doc.scrollWidth - limit) + 'px',
      ];

      if (guilty.length) {
        guilty.sort(function (a, b) { return b.right - a.right; });
        guilty.slice(0, 3).forEach(function (row) {
          lines.push('→ ' + row.selector
                     + '  (o\'ng cheti ' + row.right + ', kengligi ' + row.width + ')');
          row.element.style.outline = '2px solid #E5484D';
        });
        lines.push('Jami ' + guilty.length + ' ta. Batafsil — konsolda.');
        console.table(guilty.map(function (row) {
          return { selector: row.selector, right: row.right, width: row.width };
        }));
      } else {
        lines.push('Ko\'rinishdan kengroq element topilmadi.');
        lines.push('Demak sabab `position: fixed` yoki `margin` da.');
      }

      panel.textContent = lines.join('\n');
      document.body.appendChild(panel);
    });
  }

})();
