"""OCPP 1.6J WebSocket consumer — haqiqiy charger'lar shu yerga ulanadi.

Oqim: charger `wss://<host>/ws/ocpp/<ocpp_id>/` manziliga `ocpp1.6` subprotokol
bilan ulanadi -> BootNotification yuboradi -> biz Accepted javob beramiz ->
charger davriy Heartbeat/StatusNotification yuboradi -> foydalanuvchi zaryadlashni
boshlaganda charger StartTransaction/MeterValues/StopTransaction yuboradi.

Central System -> Charge Point buyruqlari (RemoteStartTransaction va h.k.)
`commands.py` orqali channel layer group'iga yuboriladi va shu yerdagi
`ocpp_command` handler orqali chargerga jo'natiladi (qarang: dashboard'dagi
"Masofadan boshlash/to'xtatish" tugmalari).
"""

import json
import logging
import uuid
from datetime import datetime, timezone as dt_timezone

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from . import protocol

logger = logging.getLogger('ocpp_gateway')

# OCPP 1.6 errorCode -> foydalanuvchiga ko'rsatiladigan sabab. Mobil ilova bu
# matnni ulagich holati oynasida ("Ulagich ishlamayapti") to'g'ridan-to'g'ri
# chiqaradi, shuning uchun texnik kod emas, oddiy tilda yoziladi.
OCPP_ERROR_REASONS = {
    'ConnectorLockFailure': "Ulagich qulfi ishlamayapti — kabel mahkamlanmadi.",
    'EVCommunicationError': "Avtomobil bilan aloqa uzildi.",
    'GroundFailure': "Yerga ulanishda nosozlik aniqlandi.",
    'HighTemperature': "Qurilma qizib ketdi, sovushini kutmoqda.",
    'InternalError': "Zaryadlash qurilmasida ichki nosozlik.",
    'OverCurrentFailure': "Tok me'yordan oshib ketdi.",
    'OverVoltage': "Kuchlanish me'yordan yuqori.",
    'UnderVoltage': "Kuchlanish me'yordan past.",
    'PowerMeterFailure': "Hisoblagich ishlamayapti.",
    'PowerSwitchFailure': "Quvvat kalitida nosozlik.",
    'ReaderFailure': "Karta o'quvchi ishlamayapti.",
    'ResetFailure': "Qurilmani qayta ishga tushirib bo'lmadi.",
    'WeakSignal': "Aloqa signali kuchsiz.",
}


# Ichki idTag prefikslari — bular RFID karta emas, bizning tizimimiz
# yuborgan belgilar (mobil ilova va panel). Ular ro'yxatdan tekshirilmaydi.
INTERNAL_TAG_PREFIXES = ('APP-', 'DASH-')


class ChargerLogKind:
    """`stations.ChargerLog.Kind` ning qisqartmasi.

    Consumer modul darajasida Django modelini import qila olmaydi (ilova hali
    yuklanmagan bo'lishi mumkin), shuning uchun jurnal turlari shu yerda
    matn sifatida takrorlanadi. Qiymatlar model bilan bir xil bo'lishi shart —
    buni test tekshiradi.
    """

    BOOT = 'boot'
    STATUS = 'status'
    STOP = 'stop'
    FIRMWARE = 'firmware'
    DIAGNOSTICS = 'diagnostics'
    ERROR = 'error'
    OTHER = 'other'


def _is_fault(ocpp_status, error_code) -> bool:
    """Bu xabar nosozlik haqidami — jurnalda ajratib ko'rsatish uchun."""
    return bool(error_code and error_code != 'NoError') or ocpp_status == 'Faulted'


def _offline_reason(ocpp_status, error_code):
    """StatusNotification'dagi status/errorCode juftligini o'qiladigan sababga aylantiradi."""
    if error_code and error_code != 'NoError':
        return OCPP_ERROR_REASONS.get(error_code, f'Nosozlik: {error_code}')
    if ocpp_status == 'Unavailable':
        return "Ulagich vaqtincha xizmatdan chiqarilgan."
    return "Ulagichda nosozlik aniqlandi."


class OCPPConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.ocpp_id = self.scope['url_route']['kwargs']['ocpp_id']
        self.group_name = f'ocpp_{self.ocpp_id}'
        self._pending_calls = {}  # bizning CALL'larimizga kutilayotgan javoblar
        self._sent_actions = {}  # unique_id -> yuborilgan buyruq nomi

        station = await self._get_station(self.ocpp_id)
        if station is None:
            logger.warning("OCPP: noma'lum ocpp_id bilan ulanishga urinish: %s", self.ocpp_id)
            await self.close(code=4001)
            return

        # Parol tekshiruvi. Ilgari ulanish uchun FAQAT `ocpp_id` ni bilish
        # yetardi, u esa maxfiy emas: qurilma ustida yozilgan, panelda
        # ko'rinadi va odatda ketma-ket. Soxta "charger" ulanib begona
        # odamning hamyonidan pul yechishi mumkin edi.
        allowed, reason = await self._check_credentials(station)
        if not allowed:
            logger.warning('OCPP: ulanish rad etildi (ocpp_id=%s): %s',
                           self.ocpp_id, reason)
            await self._log_rejected(station.id, reason)
            # 4003 — "ruxsat yo'q". Charger buni qayta ulanish sababi deb
            # qaraydi, shuning uchun sabab logda va panelda qoladi.
            await self.close(code=4003)
            return

        self.station_id = station.id

        # OCPP 1.6J shart qiladi: klient `Sec-WebSocket-Protocol: ocpp1.6` yuboradi,
        # server ham xuddi shu subprotokolni tanlab javob berishi kerak.
        requested = self.scope.get('subprotocols', [])
        subprotocol = protocol.SUBPROTOCOL if protocol.SUBPROTOCOL in requested else None

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept(subprotocol=subprotocol)
        await self._touch_last_seen()
        logger.info('OCPP: charger ulandi (ocpp_id=%s)', self.ocpp_id)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info('OCPP: charger uzildi (ocpp_id=%s, code=%s)', getattr(self, 'ocpp_id', '?'), close_code)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            raw = json.loads(text_data)
            message_type, unique_id, action_or_error, payload = protocol.parse_message(raw)
        except (json.JSONDecodeError, protocol.OCPPError) as exc:
            logger.warning('OCPP: yaroqsiz xabar (ocpp_id=%s): %s', getattr(self, 'ocpp_id', '?'), exc)
            return

        await self._touch_last_seen()

        if message_type == protocol.CALL:
            await self._handle_call(unique_id, action_or_error, payload)
        elif message_type == protocol.CALLRESULT:
            await self._handle_call_result(unique_id, payload)
        elif message_type == protocol.CALLERROR:
            await self._handle_call_result(unique_id, {'error': action_or_error, **payload})

    # ─── Bizning chargerga yuborgan buyruqlarimizga javob kelganda ────────
    def _resolve_pending(self, unique_id, payload):
        future = self._pending_calls.pop(unique_id, None)
        if future and not future.done():
            future.set_result(payload)

    async def _handle_call_result(self, unique_id, payload):
        """Chargerning bizning buyrug'imizga javobi.

        Ilgari javob shunchaki tashlab yuborilardi — buyruq bajarildimi yoki
        yo'qmi bilib bo'lmasdi. Endi qaysi buyruqqa javob kelgani eslab
        qolinadi va ma'lumot qaytaradigan buyruqlar (GetConfiguration) natijasi
        saqlanadi.
        """
        self._resolve_pending(unique_id, payload)
        action = self._sent_actions.pop(unique_id, None)
        if action is None:
            return

        if payload.get('error'):
            await self._log(ChargerLogKind.ERROR, action,
                            f"{action} rad etildi: {payload.get('error')}", payload)
            return

        if action == 'GetConfiguration':
            saved = await self._save_configuration(payload)
            await self._log(ChargerLogKind.OTHER, action,
                            f'Sozlamalar o\'qildi: {saved} ta kalit', payload)
        elif action == 'ChangeConfiguration':
            await self._log(ChargerLogKind.OTHER, action,
                            f"Sozlama o'zgartirish: {payload.get('status', '')}", payload)

    # ─── Dashboard'dan kelgan "buyruq yubor" xabari (group_send) ─────────
    async def ocpp_command(self, event):
        """commands.py -> channel_layer.group_send(..., {'type': 'ocpp.command', ...})"""
        unique_id = uuid.uuid4().hex
        # Javob kelganda qaysi buyruqqa tegishli ekanini bilish uchun eslab qolamiz.
        # Lug'at cheksiz o'smasin — javobsiz qolgan eng eskilari chiqarib tashlanadi.
        if len(self._sent_actions) > 100:
            self._sent_actions.pop(next(iter(self._sent_actions)), None)
        self._sent_actions[unique_id] = event['action']

        await self.send(text_data=json.dumps(protocol.encode_call(unique_id, event['action'], event['payload'])))
        logger.info('OCPP: buyruq yuborildi (ocpp_id=%s): %s %s', self.ocpp_id, event['action'], event['payload'])

    # ─── Charger CALL yuborganda — action bo'yicha handler'ga yo'naltirish ─
    async def _handle_call(self, unique_id, action, payload):
        handler = getattr(self, f'on_{_to_snake_case(action)}', None)
        if handler is None:
            logger.info("OCPP: qo'llab-quvvatlanmaydigan action: %s (ocpp_id=%s)", action, self.ocpp_id)
            await self.send(text_data=json.dumps(
                protocol.encode_call_error(unique_id, 'NotSupported', f"{action} qo'llab-quvvatlanmaydi")
            ))
            return
        try:
            response = await handler(payload)
        except protocol.OCPPError as exc:
            await self.send(text_data=json.dumps(
                protocol.encode_call_error(unique_id, exc.error_code, exc.description)
            ))
            return
        except Exception:
            logger.exception('OCPP: %s handler xato berdi (ocpp_id=%s)', action, self.ocpp_id)
            await self.send(text_data=json.dumps(
                protocol.encode_call_error(unique_id, 'InternalError', 'Serverda kutilmagan xatolik')
            ))
            return
        await self.send(text_data=json.dumps(protocol.encode_call_result(unique_id, response)))

    # ═══════════════════════════════════════════════════════════════════
    # OCPP 1.6 action handler'lari — Charge Point -> Central System
    # ═══════════════════════════════════════════════════════════════════

    async def on_boot_notification(self, payload):
        logger.info(
            'OCPP BootNotification (ocpp_id=%s): vendor=%s model=%s fw=%s',
            self.ocpp_id, payload.get('chargePointVendor'),
            payload.get('chargePointModel'), payload.get('firmwareVersion'),
        )
        # Qurilma pasporti — ilgari bu ma'lumot faqat logga tushib yo'qolardi
        await self._save_boot_info(payload)
        return {
            'status': 'Accepted',
            'currentTime': _ocpp_timestamp(),
            'interval': 300,  # soniyada — chargerga shu oraliqda Heartbeat yuborishni aytamiz
        }

    async def on_heartbeat(self, payload):
        return {'currentTime': _ocpp_timestamp()}

    async def on_firmware_status_notification(self, payload):
        """Proshivka yangilanish bosqichi: Downloading / Installing / Installed / *Failed."""
        await self._save_device_status('firmware', payload.get('status', ''))
        await self._log(ChargerLogKind.FIRMWARE, 'FirmwareStatusNotification',
                        f"Proshivka: {payload.get('status', '')}", payload)
        return {}

    async def on_diagnostics_status_notification(self, payload):
        """Diagnostika faylini yuklash bosqichi: Uploading / Uploaded / UploadFailed."""
        await self._save_device_status('diagnostics', payload.get('status', ''))
        await self._log(ChargerLogKind.DIAGNOSTICS, 'DiagnosticsStatusNotification',
                        f"Diagnostika: {payload.get('status', '')}", payload)
        return {}

    async def on_status_notification(self, payload):
        connector_id = payload.get('connectorId')
        status = payload.get('status')  # Available/Preparing/Charging/Faulted/Unavailable/...
        error_code = payload.get('errorCode')

        if connector_id not in (None, 0):  # 0 — charger'ning o'zi haqida, ulagich emas
            await self._update_connector_status(connector_id, status, error_code)

        # Har bir holat o'zgarishi jurnalga tushadi. Modeldagi maydonlarga
        # `vendorId`, `vendorErrorCode` va `info` sig'maydi — ular ishlab
        # chiqaruvchiga xos va nosozlik tahlilida aynan shular kerak bo'ladi.
        target = f'Ulagich {connector_id}' if connector_id else 'Charger'
        summary = f'{target}: {status}'
        if error_code and error_code != 'NoError':
            summary += f' ({error_code})'
        kind = ChargerLogKind.ERROR if _is_fault(status, error_code) else ChargerLogKind.STATUS
        await self._log(kind, 'StatusNotification', summary, payload)
        return {}

    async def on_authorize(self, payload):
        """Charger kartani tekshirishni so'raydi.

        Ilgari bu yer har qanday kartani qabul qilardi — ya'ni istalgan RFID
        bilan bepul zaryadlash mumkin edi. Endi karta ro'yxatdan qidiriladi.
        """
        status = await self._authorize_tag(payload.get('idTag', ''))
        return {'idTagInfo': {'status': status}}

    async def on_start_transaction(self, payload):
        connector_id = payload.get('connectorId')
        id_tag = payload.get('idTag', '')
        meter_start = payload.get('meterStart', 0)

        session = await self._start_live_session(connector_id, id_tag, meter_start)
        if session is None:
            raise protocol.OCPPError('PropertyConstraintViolation', "Noma'lum connectorId")

        return {
            'transactionId': session.id,
            'idTagInfo': {'status': 'Accepted'},
        }

    async def on_meter_values(self, payload):
        transaction_id = payload.get('transactionId')
        if transaction_id is None:
            return {}

        samples = _extract_samples(payload.get('meterValue', []))
        if samples.get('energy_wh') is not None:
            await self._update_live_meter(transaction_id, samples['energy_wh'])
        # O'lchov tarixi — panelda kuchlanish/tok dinamikasi shundan chiziladi.
        # Energiya kelmagan bo'lsa ham qolgan qiymatlar saqlanadi.
        if samples:
            await self._record_reading(transaction_id, samples)
        return {}

    async def on_stop_transaction(self, payload):
        transaction_id = payload.get('transactionId')
        meter_stop = payload.get('meterStop')
        reason = payload.get('reason', '')

        # Tugash oldidan yuborilgan oxirgi o'lchovlar. Ular `transactionData`
        # ichida keladi va sessiya yopilgandan keyin boshqa hech qayerdan
        # kelmaydi — shuning uchun yopishdan OLDIN yozib olinadi.
        for entry in payload.get('transactionData', []):
            samples = _extract_samples([entry])
            if samples:
                await self._record_reading(transaction_id, samples)

        await self._stop_live_session(transaction_id, meter_stop, reason)
        await self._log(
            ChargerLogKind.STOP, 'StopTransaction',
            f'Sessiya #{transaction_id} tugadi{f" ({reason})" if reason else ""}', payload,
        )
        return {'idTagInfo': {'status': 'Accepted'}}

    async def on_data_transfer(self, payload):
        return {'status': 'UnknownVendorId'}

    # ═══════════════════════════════════════════════════════════════════
    # DB yordamchilari (sync ORM -> async consumer ko'prigi)
    # ═══════════════════════════════════════════════════════════════════

    @database_sync_to_async
    def _get_station(self, ocpp_id):
        from stations.models import Station
        return Station.objects.filter(ocpp_id=ocpp_id).first()

    def _basic_credentials(self):
        """Handshake'dagi `Authorization: Basic` sarlavhasi.

        `(login, parol)` yoki sarlavha bo'lmasa `(None, None)`.
        """
        import base64

        for name, value in self.scope.get('headers', []):
            if name.lower() != b'authorization':
                continue
            try:
                raw = value.decode('latin-1')
                if not raw.lower().startswith('basic '):
                    return None, None
                decoded = base64.b64decode(raw[6:]).decode('utf-8')
            except (ValueError, UnicodeDecodeError):
                return None, None
            login, _, password = decoded.partition(':')
            return login, password
        return None, None

    @database_sync_to_async
    def _check_credentials(self, station):
        """Charger o'zini to'g'ri tanishtirdimi. `(ruxsat, sabab)`."""
        import secrets

        from management.models import SiteSettings

        settings_obj = SiteSettings.load()

        if not station.ocpp_password:
            if settings_obj.require_ocpp_auth:
                return False, ('stansiyaga OCPP paroli qo\'yilmagan '
                               '(Stansiya sahifasida belgilang)')
            # Parol yo'q va majburiy emas — eski qurilmalar uchun yo'l
            # ochiq qoladi, lekin bu Tizim holatida ko'rinib turadi
            return True, ''

        login, password = self._basic_credentials()
        if password is None:
            return False, 'parol yuborilmadi'

        # Doimiy vaqtli solishtirish: oddiy `==` birinchi mos kelmagan
        # belgida to'xtaydi va javob vaqti parol haqida ma'lumot beradi
        if not secrets.compare_digest(password, station.ocpp_password):
            return False, "parol noto'g'ri"
        # Login ixtiyoriy: ba'zi qurilmalar uni yubormaydi. Yuborilgan
        # bo'lsa `ocpp_id` ga mos kelishi kerak.
        if login and not secrets.compare_digest(login, station.ocpp_id or ''):
            return False, 'login mos kelmadi'

        return True, ''

    @database_sync_to_async
    def _log_rejected(self, station_id, reason):
        """Rad etilgan ulanishni yozib qo'yadi.

        Aks holda kimdir manzilni topib, parol tanlayotganini bilishning
        iloji bo'lmasdi.
        """
        from stations.models import ChargerLog

        try:
            ChargerLog.objects.create(
                station_id=station_id, kind=ChargerLog.Kind.OTHER,
                action='Connect', summary=f'Ulanish rad etildi: {reason}'[:200],
                payload={'reason': reason},
            )
        except Exception:       # noqa: BLE001 — yozuv ulanishni buzmasin
            pass

    @database_sync_to_async
    def _authorize_tag(self, id_tag):
        """Kartani ro'yxatdan tekshiradi va OCPP holatini qaytaradi.

        Uch xil idTag bo'ladi:
          * `APP-<user id>` — mobil ilova boshlagan sessiya (ichki, tekshirilmaydi);
          * `DASH-<login>` — panel orqali boshlangan (ichki);
          * qolgani — haqiqiy RFID karta, ro'yxatdan qidiriladi.

        Noma'lum karta ro'yxatga "tasdiqlanmagan" bo'lib qo'shiladi — shunda
        operator qaysi kartalar ishlatilayotganini ko'radi va ularni birma-bir
        tasdiqlaydi. Qat'iy rejim (Sozlamalar > Xavfsizlik) yoqilmaguncha
        bunday karta ishlayveradi.
        """
        from accounts.models import RfidCard
        from management.models import SiteSettings
        from stations.models import ChargerLog

        id_tag = (id_tag or '').strip()
        if not id_tag:
            return 'Invalid'
        if id_tag.startswith(INTERNAL_TAG_PREFIXES):
            return 'Accepted'

        strict = SiteSettings.load().require_known_rfid
        card = RfidCard.objects.filter(id_tag=id_tag).first()

        if card is None:
            card = RfidCard.objects.create(
                id_tag=id_tag[:20], status=RfidCard.Status.PENDING,
                first_seen_station_id=self.station_id,
            )
            ChargerLog.objects.create(
                station_id=self.station_id, kind=ChargerLog.Kind.OTHER, action='Authorize',
                summary=f"Yangi karta ko'rindi: {id_tag}"[:200],
                payload={'idTag': id_tag, 'strict': strict},
            )

        status = card.ocpp_status()
        if status == 'Pending':
            # Qat'iy rejimda tasdiqlanmagan karta ishlamaydi
            status = 'Invalid' if strict else 'Accepted'

        # Bitta karta bir vaqtda ikki joyda ishlamasin. OCPP'da shu holat
        # uchun maxsus javob bor — charger uni foydalanuvchiga tushunarli
        # qilib ko'rsatadi.
        if status == 'Accepted':
            from sessions_app.models import ChargingSession

            if ChargingSession.objects.filter(
                id_tag=id_tag, status=ChargingSession.Status.CHARGING
            ).exists():
                status = 'ConcurrentTx'

        # Boshlash qoidalari: balans (minimal chegara bilan) va ish vaqti.
        # Ular sozlamalarda turadi va uch joyda bir xil qo'llanadi —
        # karta, mobil ilova va panel (`stations.rules`).
        #
        # Mobil ilovada foydalanuvchi balansini ekranda ko'radi, karta bilan
        # esa ko'rmaydi — sessiya tugagach "qarz" bo'lib qolardi. Xizmat
        # kartasi (egasi ham, kompaniyasi ham yo'q) balans tekshiruvidan o'tmaydi.
        if status == 'Accepted':
            from stations.rules import can_start

            reason = can_start(card.billing_user, card=card)
            if reason:
                status = 'Blocked'
                ChargerLog.objects.create(
                    station_id=self.station_id, kind=ChargerLog.Kind.OTHER,
                    action='Authorize', summary=f'Rad etildi: {reason}'[:200],
                    payload={'idTag': id_tag, 'reason': reason},
                )

        if status == 'Accepted':
            card.use_count += 1
            card.last_used_at = timezone.now()
            card.save(update_fields=['use_count', 'last_used_at'])
        else:
            ChargerLog.objects.create(
                station_id=self.station_id, kind=ChargerLog.Kind.OTHER, action='Authorize',
                summary=f'Karta rad etildi: {id_tag} ({status})'[:200],
                payload={'idTag': id_tag, 'status': status},
            )
        return status

    @database_sync_to_async
    def _log(self, kind, action, summary, payload):
        """Xom xabarni jurnalga yozadi.

        Jurnal hech qachon asosiy oqimni to'xtatmasligi kerak — yozib
        bo'lmasa xato logga tushadi, xolos.
        """
        from stations.models import ChargerLog

        try:
            ChargerLog.objects.create(
                station_id=self.station_id, kind=kind, action=action,
                summary=summary[:200], payload=payload,
            )
        except Exception:
            logger.exception('OCPP: jurnalga yozib bo\'lmadi (ocpp_id=%s)', self.ocpp_id)

    @database_sync_to_async
    def _save_boot_info(self, payload):
        """BootNotification'dagi pasport ma'lumotini saqlaydi.

        Charger har qayta yuklanganda yuboradi, shuning uchun `boot_count`
        oshib boradi — bu son tez o'ssa qurilma beqaror ishlayotgan bo'ladi.
        Bo'sh kelgan maydonlar eskisini o'chirmaydi.
        """
        from stations.models import ChargerInfo, ChargerLog

        info, created = ChargerInfo.objects.get_or_create(station_id=self.station_id)

        fields = {
            'vendor': payload.get('chargePointVendor'),
            'model': payload.get('chargePointModel'),
            'serial_number': payload.get('chargePointSerialNumber'),
            'charge_box_serial': payload.get('chargeBoxSerialNumber'),
            'firmware_version': payload.get('firmwareVersion'),
            'iccid': payload.get('iccid'),
            'imsi': payload.get('imsi'),
            'meter_type': payload.get('meterType'),
            'meter_serial': payload.get('meterSerialNumber'),
        }
        changed = []
        for name, value in fields.items():
            if value:
                setattr(info, name, str(value)[:100])
                changed.append(name)

        now = timezone.now()
        info.boot_count += 1
        info.last_boot_at = now
        changed += ['boot_count', 'last_boot_at']
        if info.first_boot_at is None:
            info.first_boot_at = now
            changed.append('first_boot_at')
        info.save(update_fields=changed)

        ChargerLog.objects.create(
            station_id=self.station_id, kind=ChargerLog.Kind.BOOT,
            action='BootNotification',
            summary=f"{info.title} · proshivka {info.firmware_version or '—'}"[:200],
            payload=payload,
        )

    @database_sync_to_async
    def _save_configuration(self, payload):
        """GetConfiguration javobini saqlaydi.

        Charger ikki ro'yxat qaytaradi: `configurationKey` — bilgan kalitlari
        qiymati bilan, `unknownKey` — u qo'llab-quvvatlamaydigan kalitlar.
        Ikkalasi ham saqlanadi: operator nima MAVJUD emasligini ham bilishi
        kerak, aks holda "nega sozlab bo'lmayapti" degan savol javobsiz qoladi.
        """
        from stations.models import ChargerConfiguration

        seen = []
        for entry in payload.get('configurationKey', []):
            key = entry.get('key')
            if not key:
                continue
            ChargerConfiguration.objects.update_or_create(
                station_id=self.station_id, key=key[:100],
                defaults={
                    'value': str(entry.get('value', ''))[:500],
                    'is_readonly': bool(entry.get('readonly')),
                    'is_unknown': False,
                },
            )
            seen.append(key[:100])

        for key in payload.get('unknownKey', []):
            ChargerConfiguration.objects.update_or_create(
                station_id=self.station_id, key=str(key)[:100],
                defaults={'value': '', 'is_readonly': True, 'is_unknown': True},
            )
            seen.append(str(key)[:100])

        # Chargerdan olib tashlangan kalitlar bizda osilib qolmasin
        if seen:
            ChargerConfiguration.objects.filter(
                station_id=self.station_id
            ).exclude(key__in=seen).delete()
        return len(seen)

    @database_sync_to_async
    def _save_device_status(self, kind, status):
        from stations.models import ChargerInfo

        info, _ = ChargerInfo.objects.get_or_create(station_id=self.station_id)
        if kind == 'firmware':
            info.firmware_status = status[:40]
            info.firmware_status_at = timezone.now()
            info.save(update_fields=['firmware_status', 'firmware_status_at'])
        else:
            info.diagnostics_status = status[:40]
            info.diagnostics_status_at = timezone.now()
            info.save(update_fields=['diagnostics_status', 'diagnostics_status_at'])

    @database_sync_to_async
    def _touch_last_seen(self):
        from stations.models import Station
        Station.objects.filter(id=self.station_id).update(ocpp_last_seen_at=timezone.now())

    @database_sync_to_async
    def _update_connector_status(self, ocpp_connector_id, ocpp_status, error_code):
        from stations.models import Connector

        status_map = {
            'Available': Connector.Status.AVAILABLE,
            'Preparing': Connector.Status.AVAILABLE,
            'Charging': Connector.Status.CHARGING,
            'SuspendedEVSE': Connector.Status.CHARGING,
            # SuspendedEV — avtomobil endi quvvat qabul qilmayapti (odatda batareya
            # to'lgan), lekin kabel hali ulangan. Finishing — tranzaksiya tugadi,
            # kabel hali uzilmagan. Ikkalasida ham ulagich jismonan BAND bo'lib
            # qoladi, shuning uchun 'available' emas — pullik parkovka rejimi.
            'SuspendedEV': Connector.Status.CHARGING,
            'Finishing': Connector.Status.CHARGING,
            'Faulted': Connector.Status.OFFLINE,
            'Unavailable': Connector.Status.OFFLINE,
            # Bron bo'yicha ushlab turilgan: jismonan bo'sh, lekin faqat
            # bron egasi boshlay oladi.
            'Reserved': Connector.Status.RESERVED,
        }
        # Kabel ulangan holicha "kutish" holatlari — parkovka hisoblagichi shu
        # yerdan boshlanadi (stations.Connector.parking_since).
        parking_statuses = {'SuspendedEV', 'Finishing'}

        connector = Connector.objects.filter(station_id=self.station_id, ocpp_connector_id=ocpp_connector_id).first()
        if connector is None:
            logger.warning(
                "OCPP: station=%s uchun ocpp_connector_id=%s bilan Connector topilmadi",
                self.station_id, ocpp_connector_id,
            )
            return
        mapped = status_map.get(ocpp_status)
        if not mapped:
            return

        fields = ['status', 'parking_started_at', 'offline_reason']
        connector.status = mapped

        if ocpp_status in parking_statuses:
            # Takroriy StatusNotification hisoblagichni nolga qaytarmasligi kerak
            if connector.parking_started_at is None:
                connector.parking_started_at = timezone.now()
        else:
            connector.parking_started_at = None

        if mapped == Connector.Status.OFFLINE:
            connector.offline_reason = _offline_reason(ocpp_status, error_code)
        else:
            connector.offline_reason = ''

        connector.save(update_fields=fields)

        # Profilaktika yozuvi. Ulagich holati o'z-o'zidan tarix qoldirmaydi —
        # tuzalgan zahoti sabab ham, qachon buzilgani ham yo'qoladi. Shu sabab
        # nosozlik alohida jadvalga yoziladi va operator uni panelda ko'radi.
        from stations.maintenance import open_issue, resolve_open_issues

        if mapped == Connector.Status.OFFLINE:
            open_issue(
                station=connector.station, connector=connector,
                reason=connector.offline_reason, error_code=error_code or '',
            )
        else:
            resolve_open_issues(
                station=connector.station, connector=connector,
                note=f'Qurilma "{ocpp_status}" holatini yubordi',
            )

    @database_sync_to_async
    def _start_live_session(self, ocpp_connector_id, id_tag, meter_start):
        from accounts.models import RfidCard
        from django.contrib.auth.models import User
        from stations.models import Connector
        from sessions_app.models import ChargingSession

        connector = Connector.objects.select_related('station').filter(
            station_id=self.station_id, ocpp_connector_id=ocpp_connector_id
        ).first()
        if connector is None:
            return None

        # Sessiya KIMGA yozilishi idTag'dan aniqlanadi:
        #   `APP-<id>`  — mobil ilova boshlagan, foydalanuvchi to'g'ridan-to'g'ri;
        #   RFID karta  — kartaning egasi (biriktirilgan bo'lsa);
        #   qolgani     — xizmat/mahalliy sessiya uchun texnik foydalanuvchi.
        #
        # Ilgari karta bo'yicha har safar `id_tag` nomli YANGI foydalanuvchi
        # yaratilardi: pul hech kimning hamyonidan yechilmasdi va bitta odamning
        # sessiyalari bir necha "hisob"ga tarqalib ketardi.
        user = None
        if id_tag.startswith('APP-'):
            user = User.objects.filter(id=id_tag[len('APP-'):]).first()
        elif id_tag and not id_tag.startswith('DASH-'):
            card = RfidCard.objects.select_related(
                'user', 'company__billing_user'
            ).filter(id_tag=id_tag).first()
            if card:
                # Korporativ kartada pul kompaniya hamyonidan yechiladi
                user = card.billing_user
        if user is None:
            username = id_tag or f'ocpp-{self.station_id}-{ocpp_connector_id}'
            user, _ = User.objects.get_or_create(username=username)

        connector.status = Connector.Status.CHARGING
        connector.save(update_fields=['status'])

        # Qaysi mashina zaryadlanayotgani — foydalanuvchining standart mashinasi.
        # Charger buni bilmaydi, shuning uchun profil ma'lumotidan olinadi.
        from sessions_app.services import vehicle_snapshot

        vehicle, vehicle_label, vehicle_vin = vehicle_snapshot(user)

        # Narx shu yerda muzlatiladi: tarif oynasi va aksiya sessiya
        # BOSHLANGAN paytdagi holat bo'yicha olinadi. Ilovadan masofadan
        # boshlansa, foydalanuvchi kiritgan promo-kod shu yerda kutib
        # turadi (`PendingPromo`) — aks holda u yo'lda yo'qolardi.
        from sessions_app.models import PendingPromo
        from stations import pricing

        promo_code = PendingPromo.take(user, connector.station)
        quote = pricing.resolve(connector.station, promo_code=promo_code)

        session = ChargingSession.objects.create(
            user=user,
            station=connector.station,
            connector=connector,
            start_percent=0,
            power_kw=connector.power_kw,
            price_per_kwh=quote.price,
            base_price_per_kwh=quote.base,
            offer=quote.offer,
            price_label=quote.label[:200],
            connector_label=connector.label,
            vehicle=vehicle,
            vehicle_label=vehicle_label,
            vehicle_vin=vehicle_vin,
            is_live=True,
            id_tag=id_tag,
            meter_start_wh=meter_start,
            live_meter_wh=meter_start,
        )
        return session

    @database_sync_to_async
    def _update_live_meter(self, transaction_id, meter_wh):
        from sessions_app.models import ChargingSession
        ChargingSession.objects.filter(id=transaction_id, status=ChargingSession.Status.CHARGING).update(
            live_meter_wh=meter_wh
        )

    @database_sync_to_async
    def _record_reading(self, transaction_id, samples):
        """Bitta o'lchovni tarixga yozadi (panel grafigi uchun).

        Sessiya topilmasa jimgina o'tkazib yuboriladi — charger tugagan
        tranzaksiya bo'yicha kechikkan xabar yuborishi mumkin.
        """
        from sessions_app.models import ChargingSession, SessionMeterReading

        if not ChargingSession.objects.filter(id=transaction_id).exists():
            return
        SessionMeterReading.objects.create(session_id=transaction_id, **{
            field: samples.get(field) for field in (
                'voltage_v', 'current_a', 'power_kw', 'energy_wh', 'soc_percent',
                'voltage_l1_v', 'voltage_l2_v', 'voltage_l3_v',
                'temperature_c', 'frequency_hz',
                'current_offered_a', 'power_offered_kw',
            )
        })

    @database_sync_to_async
    def _stop_live_session(self, transaction_id, meter_stop, reason=''):
        from sessions_app.models import ChargingSession

        session = ChargingSession.objects.filter(id=transaction_id).first()
        if session is None or session.status != ChargingSession.Status.CHARGING:
            return
        if meter_stop is not None:
            session.live_meter_wh = meter_stop
            session.meter_stop_wh = meter_stop
        if reason:
            session.stop_reason = reason[:30]
        session.stop()  # hamyon/tranzaksiya/ulagichni bo'shatishni ham o'z ichiga oladi


def _to_snake_case(action: str) -> str:
    result = []
    for i, ch in enumerate(action):
        if ch.isupper() and i > 0:
            result.append('_')
        result.append(ch.lower())
    return ''.join(result)


def _ocpp_timestamp() -> str:
    return datetime.now(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# OCPP measurand -> bizdagi maydon va birlikni asosiy o'lchovga keltirish
# koeffitsienti. Charger qaysi o'lchovlarni yuborishi uning
# `MeterValuesSampledData` sozlamasiga bog'liq — hech biri majburiy emas.
_MEASURANDS = {
    'Energy.Active.Import.Register': ('energy_wh', {'Wh': 1, 'kWh': 1000}),
    'Voltage': ('voltage_v', {'V': 1, 'kV': 1000}),
    'Current.Import': ('current_a', {'A': 1}),
    'Power.Active.Import': ('power_kw', {'W': 0.001, 'kW': 1}),
    'SoC': ('soc_percent', {'Percent': 1, '': 1}),
    'Temperature': ('temperature_c', {'Celsius': 1, 'Celcius': 1, '': 1}),
    'Frequency': ('frequency_hz', {'Hz': 1, '': 1}),
    # Charger avtomobilga TAKLIF qilgan chegara. Haqiqiy tokdan sezilarli
    # farq qilsa — cheklov avtomobil tomonidan, qurilmada emas.
    'Current.Offered': ('current_offered_a', {'A': 1}),
    'Power.Offered': ('power_offered_kw', {'W': 0.001, 'kW': 1}),
}

# Uch fazali AC chargerlar kuchlanishni faza bo'yicha yuboradi. `phase`
# maydoni "L1", "L1-N" yoki "L1-L2" ko'rinishida bo'lishi mumkin, shuning
# uchun boshidagi ikki belgi bo'yicha aniqlanadi.
_PHASE_FIELDS = {'L1': 'voltage_l1_v', 'L2': 'voltage_l2_v', 'L3': 'voltage_l3_v'}


def _extract_samples(meter_values: list) -> dict:
    """MeterValues'dan bizga kerakli o'lchovlarni ajratib oladi.

    Bitta xabarda bir nechta vaqt nuqtasi bo'lishi mumkin; eng yangisi ustun
    turadi, shuning uchun ro'yxat teskari o'qiladi va birinchi topilgan
    qiymat saqlanadi.
    """
    result = {}
    for entry in reversed(meter_values):
        for sampled in entry.get('sampledValue', []):
            measurand = sampled.get('measurand', 'Energy.Active.Import.Register')
            mapping = _MEASURANDS.get(measurand)
            if not mapping:
                continue
            field, units = mapping
            try:
                value = float(sampled.get('value'))
            except (TypeError, ValueError):
                continue
            # Birlik ko'rsatilmasa — o'sha o'lchov uchun standart birlik
            factor = units.get(sampled.get('unit') or next(iter(units)))
            if factor is None:
                continue  # kutilmagan birlik: noto'g'ri son yozgandan ko'ra tashlab yuborgan ma'qul
            value *= factor

            # Fazali kuchlanish alohida maydonga; umumiy `voltage_v` esa
            # fazasiz qiymat bo'lmasa L1 dan olinadi.
            phase = (sampled.get('phase') or '')[:2].upper()
            if field == 'voltage_v' and phase in _PHASE_FIELDS:
                result.setdefault(_PHASE_FIELDS[phase], value)
                if phase == 'L1':
                    result.setdefault('voltage_v', value)
                continue

            result.setdefault(field, value)
    return result


def _extract_energy_wh(meter_values: list):
    """MeterValues payload'idan Energy.Active.Import.Register o'lchovini (Wh) topadi."""
    return _extract_samples(meter_values).get('energy_wh')
