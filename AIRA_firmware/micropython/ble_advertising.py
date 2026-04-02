# Helpers for generating BLE advertising payloads.
# Based on MicroPython official examples.

from micropython import const
import struct
import bluetooth

# Advertising payload types
_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID16_COMPLETE = const(0x3)
_ADV_TYPE_UUID32_COMPLETE = const(0x5)
_ADV_TYPE_UUID128_COMPLETE = const(0x7)
_ADV_TYPE_UUID16_MORE = const(0x2)
_ADV_TYPE_UUID32_MORE = const(0x4)
_ADV_TYPE_UUID128_MORE = const(0x6)
_ADV_TYPE_APPEARANCE = const(0x19)
_ADV_MAX_PAYLOAD = const(31)


def advertising_payload(limited_disc=False, br_edr=False, name=None, services=None, appearance=0):
    """Generate a BLE advertising payload."""
    payload = bytearray()

    def _append(adv_type, value):
        nonlocal payload
        payload += struct.pack("BB", len(value) + 1, adv_type) + value

    # Flags
    _append(
        _ADV_TYPE_FLAGS,
        struct.pack("B", (0x01 if limited_disc else 0x02) + (0x18 if br_edr else 0x04)),
    )

    # Local Name
    if name:
        _append(_ADV_TYPE_NAME, name.encode() if isinstance(name, str) else name)

    # Service UUIDs
    if services:
        for uuid in services:
            b = bytes(uuid)
            if len(b) == 2:
                _append(_ADV_TYPE_UUID16_COMPLETE, b)
            elif len(b) == 4:
                _append(_ADV_TYPE_UUID32_COMPLETE, b)
            elif len(b) == 16:
                _append(_ADV_TYPE_UUID128_COMPLETE, b)

    # Appearance
    if appearance:
        _append(_ADV_TYPE_APPEARANCE, struct.pack("<h", appearance))

    if len(payload) > _ADV_MAX_PAYLOAD:
        raise ValueError("advertising payload too large")

    return payload


def decode_field(payload, adv_type):
    """Decode a specific field from advertising payload."""
    i = 0
    result = []
    while i + 1 < len(payload):
        if payload[i + 1] == adv_type:
            result.append(payload[i + 2 : i + payload[i] + 1])
        i += 1 + payload[i]
    return result


def decode_name(payload):
    """Decode the local name from advertising payload."""
    n = decode_field(payload, _ADV_TYPE_NAME)
    return n[0].decode("utf-8") if n else None


def decode_services(payload):
    """Decode service UUIDs from advertising payload."""
    services = []
    for code in (_ADV_TYPE_UUID16_COMPLETE, _ADV_TYPE_UUID32_COMPLETE, _ADV_TYPE_UUID128_COMPLETE):
        for u in decode_field(payload, code):
            services.append(bluetooth.UUID(u))
    return services
