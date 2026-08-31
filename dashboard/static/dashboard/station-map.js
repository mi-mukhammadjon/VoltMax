/* Stansiya joylashuvini xaritadan tanlash.
 *
 * Leaflet + OpenStreetMap ishlatiladi — API kalit talab qilmaydi va bepul.
 * Kutubxona FAQAT stansiya formasi ochilganda yuklanadi (lazy), shuning uchun
 * qolgan sahifalar og'irlashmaydi.
 *
 * Koordinatalar formadagi yashirin maydonlarga yoziladi:
 *   #id_latitude / #id_longitude
 */
(function () {
  'use strict';

  var LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  var LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  var TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';

  // Toshkent markazi — yangi stansiya uchun boshlang'ich nuqta
  var DEFAULT_CENTER = [41.3111, 69.2797];
  var DEFAULT_ZOOM = 12;
  var PICKED_ZOOM = 16;

  var loading = null;

  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    if (loading) return loading;

    loading = new Promise(function (resolve, reject) {
      var css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = LEAFLET_CSS;
      document.head.appendChild(css);

      var script = document.createElement('script');
      script.src = LEAFLET_JS;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
    return loading;
  }

  function fmt(value) {
    return Number(value).toFixed(6);
  }

  /* Tashqaridan ham chaqiriladi (geokodlash) — xarita hali yuklanmagan
     bo'lsa ham koordinata maydonlarga yoziladi. */
  var applyPoint = null;

  function writeInputs(lat, lng) {
    var latInput = document.getElementById('id_latitude');
    var lngInput = document.getElementById('id_longitude');
    var readout = document.getElementById('map-coords');
    if (latInput) latInput.value = fmt(lat);
    if (lngInput) lngInput.value = fmt(lng);
    if (readout) readout.textContent = fmt(lat) + ', ' + fmt(lng);
  }

  function say(message) {
    var readout = document.getElementById('map-coords');
    if (readout) readout.textContent = message;
  }

  function init(container) {
    var latInput = document.getElementById('id_latitude');
    var lngInput = document.getElementById('id_longitude');
    var readout = document.getElementById('map-coords');
    if (!latInput || !lngInput) return;

    // Yagona manba — yashirin maydonlar. Shablonda `{{ }}` orqali
    // takrorlash lokal formatlash tufayli vergulli qiymat berardi.
    var startLat = parseFloat(latInput.value);
    var startLng = parseFloat(lngInput.value);
    var hasPoint = !isNaN(startLat) && !isNaN(startLng);

    var map = L.map(container, { scrollWheelZoom: true }).setView(
      hasPoint ? [startLat, startLng] : DEFAULT_CENTER,
      hasPoint ? PICKED_ZOOM : DEFAULT_ZOOM
    );

    L.tileLayer(TILES, {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap',
    }).addTo(map);

    var marker = null;

    function setPoint(lat, lng, recenter) {
      latInput.value = fmt(lat);
      lngInput.value = fmt(lng);
      if (readout) readout.textContent = fmt(lat) + ', ' + fmt(lng);

      if (marker) {
        marker.setLatLng([lat, lng]);
      } else {
        marker = L.marker([lat, lng], { draggable: true }).addTo(map);
        marker.on('dragend', function () {
          var p = marker.getLatLng();
          setPoint(p.lat, p.lng, false);
        });
      }
      if (recenter) map.setView([lat, lng], Math.max(map.getZoom(), PICKED_ZOOM));
    }

    applyPoint = setPoint;
    if (hasPoint) setPoint(startLat, startLng, false);

    map.on('click', function (e) {
      setPoint(e.latlng.lat, e.latlng.lng, false);
    });

    // Konteyner o'lchami keyin o'zgarsa (AJAX bilan qo'yilganda) — qayta hisoblash
    setTimeout(function () { map.invalidateSize(); }, 60);

  }


  /* ══ Manzil bo'yicha topish ═══════════════════════════════
     So'rov o'z serverimiz orqali ketadi (`/geocode/`) — Nominatim
     brauzerdan to'g'ridan-to'g'ri chaqirilganda `User-Agent` yo'qligi
     sababli rad etishi mumkin. Delegatsiya ishlatilgani uchun tugma
     xarita yuklanmagan holatda ham javob beradi. */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('#map-locate');
    if (!btn) return;
    e.preventDefault();

    var addressInput = document.querySelector('[name="address"]');
    var query = addressInput ? (addressInput.value || '').trim() : '';
    if (query.length < 3) {
      say('Avval manzilni kiriting');
      return;
    }

    btn.classList.add('is-busy');
    say('Qidirilmoqda...');

    fetch('/geocode/?q=' + encodeURIComponent(query), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    })
      .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (result) {
        if (!result.ok) {
          say(result.data.error || 'Manzil topilmadi');
          return;
        }
        // Xarita tayyor bo'lsa belgini ham ko'chiramiz
        if (applyPoint) {
          applyPoint(result.data.lat, result.data.lng, true);
        } else {
          writeInputs(result.data.lat, result.data.lng);
        }
      })
      .catch(function () { say("Qidiruv ishlamadi — xaritadan qo'lda belgilang"); })
      .then(function () { btn.classList.remove('is-busy'); });
  });

  /* Sahifada xarita bor bo'lsa — kutubxonani yuklab, ishga tushiramiz.
     AJAX bilan tarkib almashganda ham qayta chaqiriladi (app.js). */
  window.initStationMap = function () {
    var container = document.getElementById('station-map');
    if (!container || container.dataset.ready === '1') return;
    container.dataset.ready = '1';

    loadLeaflet()
      .then(function () { init(container); })
      .catch(function () {
        container.innerHTML =
          '<div class="map-error">Xaritani yuklab bo\'lmadi — internet aloqasini tekshiring.</div>';
        container.dataset.ready = '';
      });
  };

  document.addEventListener('DOMContentLoaded', window.initStationMap);
})();
