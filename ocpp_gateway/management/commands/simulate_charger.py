"""Haqiqiy charger hali kelmagan bo'lsa ham butun OCPP oqimini (ulanish,
BootNotification, StatusNotification, Remote/real Start-Stop, MeterValues)
uchtan-uchgacha sinash uchun soxta charge point.

Ishlatish:
  python manage.py simulate_charger CP-001
  python manage.py simulate_charger CP-001 --url ws://192.168.1.8:8000 --connectors 1,2
  python manage.py simulate_charger CP-001 --auto-start 1   # RFID bilan o'zi boshlagandek

Dashboard'dan "Masofadan boshlash" bossangiz, shu skript avtomatik StartTransaction
yuborib, MeterValues bilan energiya oshib borishini simulyatsiya qiladi.
Ctrl+C bilan to'xtatiladi (ulanish uzilsa charger "oflayn" ko'rinadi).
"""

import asyncio
import json
import random
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand

# Soxta chargerning sozlamalari: kalit -> (qiymat, faqat_o_qish).
# Haqiqiy qurilmalarda ham shu kalitlar uchraydi, shuning uchun panel
# ko'rinishini xuddi shu ro'yxat bilan sinash mumkin.
CONFIGURATION = {
    'HeartbeatInterval': ('300', False),
    'MeterValueSampleInterval': ('5', False),
    'MeterValuesSampledData': (
        'Energy.Active.Import.Register,Voltage,Current.Import,Power.Active.Import,Temperature',
        False,
    ),
    'ConnectionTimeOut': ('60', False),
    'NumberOfConnectors': ('2', True),
    'SupportedFeatureProfiles': ('Core,FirmwareManagement,RemoteTrigger', True),
    'ChargePointModel': ('SIM-1', True),
    'AuthorizeRemoteTxRequests': ('false', False),
    'LocalAuthorizeOffline': ('true', False),
    'ResetRetries': ('3', False),
}

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None


def _ts():
    return datetime.now(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Command(BaseCommand):
    help = "Haqiqiy charger o'rniga OCPP 1.6J ulanadigan test simulyatori"

    def add_arguments(self, parser):
        parser.add_argument('ocpp_id', help="Station.ocpp_id qiymati (masalan CP-001)")
        parser.add_argument('--url', default='ws://127.0.0.1:8000', help='Backend WebSocket manzili')
        parser.add_argument('--connectors', default='1', help="Vergul bilan: masalan 1,2")
        parser.add_argument('--power-kw', type=float, default=22.0, help='Simulyatsiya qilinadigan quvvat (kVt)')
        parser.add_argument('--auto-start', type=int, default=None,
                             help="Ulanishdan so'ng shu connectorId'da o'zi (RFID kabi) sessiya boshlaydi")

    def handle(self, *args, **options):
        if websockets is None:
            self.stderr.write(self.style.ERROR("`websockets` kutubxonasi o'rnatilmagan: pip install websockets"))
            return
        asyncio.run(self._run(options))

    async def _run(self, options):
        ocpp_id = options['ocpp_id']
        connectors = [int(c) for c in options['connectors'].split(',') if c.strip()]
        url = f"{options['url'].rstrip('/')}/ws/ocpp/{ocpp_id}/"

        self.stdout.write(self.style.WARNING(f'Ulanmoqda: {url} ...'))
        async with websockets.connect(url, subprotocols=['ocpp1.6']) as ws:
            self.stdout.write(self.style.SUCCESS(f'Ulandi (ocpp_id={ocpp_id})'))
            sim = ChargerSimulator(self, ws, ocpp_id, connectors, options['power_kw'])
            reader_task = asyncio.create_task(sim.reader_loop())

            await sim.boot()
            for cid in connectors:
                await sim.status_notification(cid, 'Available')

            tasks = [reader_task, asyncio.create_task(sim.heartbeat_loop())]
            if options['auto_start'] is not None:
                tasks.append(asyncio.create_task(sim.start_transaction(options['auto_start'], id_tag='SIMULATOR')))
            try:
                await asyncio.gather(*tasks)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass


class ChargerSimulator:
    def __init__(self, command, ws, ocpp_id, connectors, power_kw):
        self.command = command
        self.ws = ws
        self.ocpp_id = ocpp_id
        self.connectors = connectors
        self.power_kw = power_kw
        self._msg_id = 0
        self._pending = {}  # unique_id -> asyncio.Future (bizning CALL'larimizga javob)
        self.active_transactions = {}  # connectorId -> {'transaction_id', 'meter_wh'}
        self.reservations = {}  # reservationId -> connectorId
        self.local_list_version = 0

    def log(self, msg):
        self.command.stdout.write(f'[{self.ocpp_id}] {msg}')

    def _next_id(self):
        self._msg_id += 1
        return f'sim-{self._msg_id}'

    async def _call(self, action, payload):
        """CALL yuboradi va shu uniqueId uchun javob kelguncha kutadi. Websocket'ni
        o'qish faqat `reader_loop()` ichida bo'ladi — shu yerda ikkinchi marta
        `recv()` chaqirilmaydi (ikkita parallel recv() websockets kutubxonasida
        xatolik beradi)."""
        unique_id = self._next_id()
        future = asyncio.get_event_loop().create_future()
        self._pending[unique_id] = future
        await self.ws.send(json.dumps([2, unique_id, action, payload]))
        self.log(f'-> {action} {payload}')
        try:
            result = await asyncio.wait_for(future, timeout=15)
        finally:
            self._pending.pop(unique_id, None)
        self.log(f'<- javob: {result}')
        return result

    async def reader_loop(self):
        """Yagona o'qish tsikli: ham bizning CALL'larimizga javoblarni, ham
        serverdan kelgan CALL'larni (RemoteStartTransaction va h.k.) shu yerda
        qabul qilamiz."""
        async for raw in self.ws:
            data = json.loads(raw)
            msg_type = data[0]

            if msg_type in (3, 4):  # CALLRESULT / CALLERROR — bizning so'rovimizga javob
                unique_id = data[1]
                future = self._pending.get(unique_id)
                if future and not future.done():
                    future.set_result(data[2] if msg_type == 3 else {'error': data[2]})
                continue

            if msg_type == 2:  # CALL — server bizdan biror narsa so'ramoqda
                _, unique_id, action, payload = data
                await self._handle_server_call(unique_id, action, payload)

    async def _handle_server_call(self, unique_id, action, payload):
        self.log(f"<- (server buyrug'i) {action} {payload}")
        if action == 'RemoteStartTransaction':
            connector_id = payload.get('connectorId') or (self.connectors[0] if self.connectors else 1)
            await self.ws.send(json.dumps([3, unique_id, {'status': 'Accepted'}]))
            asyncio.create_task(self.start_transaction(connector_id, payload.get('idTag', 'DASHBOARD')))
        elif action == 'RemoteStopTransaction':
            tx_id = payload.get('transactionId')
            connector_id = next(
                (cid for cid, s in self.active_transactions.items() if s['transaction_id'] == tx_id), None
            )
            await self.ws.send(json.dumps([3, unique_id, {'status': 'Accepted'}]))
            if connector_id is not None:
                asyncio.create_task(self.stop_transaction(connector_id))
        elif action == 'GetConfiguration':
            # Haqiqiy charger o'z sozlamalarini shu ko'rinishda qaytaradi.
            # `key` berilgan bo'lsa faqat o'shalar, aks holda hammasi.
            wanted = payload.get('key') or list(CONFIGURATION)
            known = [
                {'key': k, 'value': CONFIGURATION[k][0], 'readonly': CONFIGURATION[k][1]}
                for k in wanted if k in CONFIGURATION
            ]
            unknown = [k for k in wanted if k not in CONFIGURATION]
            result = {'configurationKey': known}
            if unknown:
                result['unknownKey'] = unknown
            await self.ws.send(json.dumps([3, unique_id, result]))
        elif action == 'ChangeConfiguration':
            key, value = payload.get('key'), str(payload.get('value', ''))
            if key not in CONFIGURATION:
                status = 'NotSupported'
            elif CONFIGURATION[key][1]:
                status = 'Rejected'  # faqat o'qish uchun
            else:
                CONFIGURATION[key] = (value, False)
                status = 'Accepted'
            await self.ws.send(json.dumps([3, unique_id, {'status': status}]))
        elif action == 'Reset':
            await self.ws.send(json.dumps([3, unique_id, {'status': 'Accepted'}]))
            self.log(f"Qayta ishga tushirish ({payload.get('type')}) — qayta boot qilinadi")
            asyncio.create_task(self.boot())
        elif action == 'ReserveNow':
            # Bron qabul qilinsa ulagich "Reserved" holatiga o'tadi
            cid = payload.get('connectorId')
            await self.ws.send(json.dumps([3, unique_id, {'status': 'Accepted'}]))
            self.reservations[payload.get('reservationId')] = cid
            await self.status_notification(cid, 'Reserved')
        elif action == 'CancelReservation':
            cid = self.reservations.pop(payload.get('reservationId'), None)
            status = 'Accepted' if cid is not None else 'Rejected'
            await self.ws.send(json.dumps([3, unique_id, {'status': status}]))
            if cid is not None:
                await self.status_notification(cid, 'Available')
        elif action in ('SetChargingProfile', 'ClearChargingProfile'):
            await self.ws.send(json.dumps([3, unique_id, {'status': 'Accepted'}]))
        elif action == 'SendLocalList':
            self.local_list_version = payload.get('listVersion', 0)
            count = len(payload.get('localAuthorizationList', []))
            self.log(f"Mahalliy ro'yxat qabul qilindi: {count} ta karta")
            await self.ws.send(json.dumps([3, unique_id, {'status': 'Accepted'}]))
        elif action == 'GetLocalListVersion':
            await self.ws.send(json.dumps([3, unique_id, {'listVersion': self.local_list_version}]))
        elif action == 'UpdateFirmware':
            await self.ws.send(json.dumps([3, unique_id, {}]))
            asyncio.create_task(self._firmware_flow())
        elif action == 'GetDiagnostics':
            await self.ws.send(json.dumps([3, unique_id, {'fileName': 'diag.log'}]))
            asyncio.create_task(self._diagnostics_flow())
        else:
            await self.ws.send(json.dumps([3, unique_id, {'status': 'Accepted'}]))

    async def _firmware_flow(self):
        """Proshivka yangilanish bosqichlari — haqiqiy qurilma ham shunday xabar beradi."""
        for status in ('Downloading', 'Downloaded', 'Installing', 'Installed'):
            await asyncio.sleep(2)
            await self._call('FirmwareStatusNotification', {'status': status})

    async def _diagnostics_flow(self):
        for status in ('Uploading', 'Uploaded'):
            await asyncio.sleep(2)
            await self._call('DiagnosticsStatusNotification', {'status': status})

    async def boot(self):
        await self._call('BootNotification', {
            'chargePointVendor': 'VoltMax-Simulator',
            'chargePointModel': 'SIM-1',
            'chargePointSerialNumber': 'SIM-SN-000123',
            'chargeBoxSerialNumber': 'BOX-000123',
            'firmwareVersion': '1.4.2',
            'iccid': '8998001234567890123',
            'imsi': '434040123456789',
            'meterType': 'AC-3P',
            'meterSerialNumber': 'MTR-77-004521',
        })

    async def status_notification(self, connector_id, status, error_code='NoError'):
        await self._call('StatusNotification', {
            'connectorId': connector_id, 'errorCode': error_code, 'status': status,
        })

    async def start_transaction(self, connector_id, id_tag='SIMULATOR'):
        if connector_id in self.active_transactions:
            return  # allaqachon boshlangan
        await self.status_notification(connector_id, 'Charging')
        result = await self._call('StartTransaction', {
            'connectorId': connector_id, 'idTag': id_tag,
            'meterStart': 0, 'timestamp': _ts(),
        })
        transaction_id = result['transactionId']
        self.log(f'Sessiya boshlandi: transactionId={transaction_id}')
        self.active_transactions[connector_id] = {'transaction_id': transaction_id, 'meter_wh': 0}
        asyncio.create_task(self._meter_loop(connector_id))

    async def _meter_loop(self, connector_id):
        """Har 5 soniyada energiya oshib boradi — RemoteStopTransaction yoki
        20 marta (~100s) dan keyin avtomatik to'xtaydi."""
        wh_per_tick = int(self.power_kw * 1000 * 5 / 3600)  # 5 soniyalik ulush
        for _ in range(20):
            await asyncio.sleep(5)
            state = self.active_transactions.get(connector_id)
            if state is None:
                return  # allaqachon to'xtatilgan
            state['meter_wh'] += wh_per_tick
            state['tick'] = state.get('tick', 0) + 1

            # Haqiqiy chargerlar bir nechta o'lchov yuboradi. Kuchlanish
            # tarmoqqa qarab bir necha foiz tebranadi, tok esa batareya
            # to'lgani sari pasayadi — panel grafigi shu dinamikani ko'rsatadi.
            voltage = 400 + random.uniform(-9, 9)
            fade = max(0.35, 1 - state['tick'] / 26)
            power_w = self.power_kw * 1000 * fade
            current = power_w / voltage

            await self._call('MeterValues', {
                'connectorId': connector_id,
                'transactionId': state['transaction_id'],
                'meterValue': [{
                    'timestamp': _ts(),
                    'sampledValue': [
                        {'value': str(state['meter_wh']),
                         'measurand': 'Energy.Active.Import.Register', 'unit': 'Wh'},
                        {'value': f'{voltage:.1f}', 'measurand': 'Voltage', 'unit': 'V'},
                        {'value': f'{current:.1f}', 'measurand': 'Current.Import', 'unit': 'A'},
                        {'value': f'{power_w:.0f}', 'measurand': 'Power.Active.Import', 'unit': 'W'},
                        {'value': f'{power_w / voltage * 1.15:.1f}',
                         'measurand': 'Current.Offered', 'unit': 'A'},
                        {'value': f'{28 + state["tick"] * 0.8:.1f}',
                         'measurand': 'Temperature', 'unit': 'Celsius'},
                        {'value': f'{50 + random.uniform(-0.15, 0.15):.2f}',
                         'measurand': 'Frequency', 'unit': 'Hz'},
                        # Uch fazali AC — har faza alohida
                        {'value': f'{voltage:.1f}', 'measurand': 'Voltage', 'unit': 'V',
                         'phase': 'L1-N'},
                        {'value': f'{voltage + random.uniform(-4, 4):.1f}',
                         'measurand': 'Voltage', 'unit': 'V', 'phase': 'L2-N'},
                        {'value': f'{voltage + random.uniform(-4, 4):.1f}',
                         'measurand': 'Voltage', 'unit': 'V', 'phase': 'L3-N'},
                    ],
                }],
            })
        await self.stop_transaction(connector_id)

    async def stop_transaction(self, connector_id):
        state = self.active_transactions.pop(connector_id, None)
        if state is None:
            return
        await self._call('StopTransaction', {
            'transactionId': state['transaction_id'],
            'idTag': 'SIMULATOR',
            'meterStop': state['meter_wh'],
            'timestamp': _ts(),
            'reason': 'Local',
            # Yakuniy o'lchovlar — bular boshqa hech qayerda kelmaydi
            'transactionData': [{
                'timestamp': _ts(),
                'sampledValue': [
                    {'value': str(state['meter_wh']),
                     'measurand': 'Energy.Active.Import.Register', 'unit': 'Wh'},
                    {'value': '399.0', 'measurand': 'Voltage', 'unit': 'V'},
                ],
            }],
        })
        await self.status_notification(connector_id, 'Available')
        self.log(f'Sessiya tugadi (connectorId={connector_id})')

    async def heartbeat_loop(self):
        while True:
            await asyncio.sleep(60)
            await self._call('Heartbeat', {})
