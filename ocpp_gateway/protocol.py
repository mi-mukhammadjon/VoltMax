"""OCPP 1.6J (JSON over WebSocket) xabar formati — https://www.openchargealliance.org

Har bir xabar JSON massiv:
  CALL       [2, "<uniqueId>", "<Action>", {payload}]
  CALLRESULT [3, "<uniqueId>", {payload}]
  CALLERROR  [4, "<uniqueId>", "<errorCode>", "<errorDescription>", {details}]

Charge Point (haqiqiy charger) har doim ulanishni o'zi boshlaydi:
  wss://<host>/ws/ocpp/<ocpp_id>/   Sec-WebSocket-Protocol: ocpp1.6
"""

CALL = 2
CALLRESULT = 3
CALLERROR = 4

SUBPROTOCOL = 'ocpp1.6'


class OCPPError(Exception):
    """CALLERROR sifatida charger'ga qaytariladigan xatolik."""

    def __init__(self, error_code: str, description: str = ''):
        self.error_code = error_code
        self.description = description
        super().__init__(f'{error_code}: {description}')


def encode_call(unique_id: str, action: str, payload: dict) -> list:
    return [CALL, unique_id, action, payload]


def encode_call_result(unique_id: str, payload: dict) -> list:
    return [CALLRESULT, unique_id, payload]


def encode_call_error(unique_id: str, error_code: str, description: str = '') -> list:
    return [CALLERROR, unique_id, error_code, description, {}]


def parse_message(raw: list):
    """[message_type, unique_id, ...] ni tekshirib, tarkibiy qismlarga ajratadi."""
    if not isinstance(raw, list) or len(raw) < 3:
        raise OCPPError('ProtocolError', "Xabar formati noto'g'ri")

    message_type = raw[0]
    unique_id = raw[1]

    if message_type == CALL:
        if len(raw) < 4:
            raise OCPPError('ProtocolError', 'CALL uchun action/payload yetishmayapti')
        return message_type, unique_id, raw[2], raw[3]
    elif message_type == CALLRESULT:
        return message_type, unique_id, None, raw[2]
    elif message_type == CALLERROR:
        return message_type, unique_id, raw[2], {'description': raw[3] if len(raw) > 3 else ''}
    raise OCPPError('ProtocolError', f"Noma'lum message type: {message_type}")
