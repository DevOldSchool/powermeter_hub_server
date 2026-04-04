import logging
import struct
from typing import List


HEADER_SIZE = 20
SENSOR_COUNT = 5
SENSOR_ID_SIZE = 3
FRAME_SIZE = 8
PADDING_MARKER = b"\xff\xff"
NO_VALUE_EPSILON = 1e-20


def _read_uint24_le(buf: bytes, offset: int) -> int:
    return buf[offset] | (buf[offset + 1] << 8) | (buf[offset + 2] << 16)


def parse_middle_endian_float(b_data: bytes) -> float:
    """
    Parse a 4-byte middle-endian float.

    The H3 bulk payload stores the value bytes as [B1, B0, B3, B2]
    relative to standard big-endian float ordering [B0, B1, B2, B3].
    """
    if len(b_data) != 4:
        raise ValueError(f"Expected 4 bytes for float, got {len(b_data)}")

    swapped = bytes([b_data[1], b_data[0], b_data[3], b_data[2]])
    value = struct.unpack(">f", swapped)[0]

    # Some H3 bulk packets encode "no value" frames that unpack to
    # denormalized near-zero floats rather than an exact 0.0.
    if abs(value) < NO_VALUE_EPSILON:
        return 0.0

    return round(value, 2)


def parse_h3bulk_payload(post_data_bytes: bytes, firmware_version: str) -> List[dict]:
    """
    Parse an H3 bulk upload into the same raw H3 units used elsewhere.

    Payload layout:
    - 4 bytes little-endian base timestamp
    - 5 sensor ids as 24-bit little-endian integers
    - 1 reserved byte
    - repeated 8-byte frames:
      - 2 bytes big-endian offset seconds from base timestamp
      - 2 bytes checksum/unknown bytes
      - 4 bytes middle-endian float value in watts

    The existing H3 text path stores values as deciwatts, so bulk values are
    converted from watts to deciwatts here before they are handed to the rest
    of the system.
    """
    if len(post_data_bytes) < HEADER_SIZE:
        logging.warning(
            "Malformed h3bulk payload: expected at least %d bytes, got %d",
            HEADER_SIZE,
            len(post_data_bytes),
        )
        return []

    base_timestamp = struct.unpack_from("<I", post_data_bytes, 0)[0]
    sensor_ids = [
        _read_uint24_le(post_data_bytes, 4 + (i * SENSOR_ID_SIZE))
        for i in range(SENSOR_COUNT)
    ]

    results = []
    cursor = HEADER_SIZE
    current_offset = None
    sensor_index = 0

    while cursor + FRAME_SIZE <= len(post_data_bytes):
        frame = post_data_bytes[cursor:cursor + FRAME_SIZE]
        if frame[0:2] == PADDING_MARKER:
            break

        offset_seconds = struct.unpack(">H", frame[0:2])[0]
        if offset_seconds != current_offset:
            current_offset = offset_seconds
            sensor_index = 0

        if sensor_index >= len(sensor_ids):
            logging.warning(
                "Skipping h3bulk frame at byte %d: sensor index %d outside header range",
                cursor,
                sensor_index,
            )
            cursor += FRAME_SIZE
            continue

        sid = sensor_ids[sensor_index]
        sensor_index += 1
        cursor += FRAME_SIZE

        if sid == 0:
            continue

        try:
            value_watts = parse_middle_endian_float(frame[4:8])
        except (struct.error, ValueError) as exc:
            logging.warning("Skipping malformed h3bulk frame at byte %d: %s", cursor - FRAME_SIZE, exc)
            continue

        # H3 text uploads store deciwatts, so bulk packet watts are scaled
        # here to keep the DB, MQTT payloads, and HA templates consistent.
        value_deciwatts = round(value_watts * 10.0, 1)

        results.append(
            {
                "type": "CT",
                "sid": str(sid),
                "label": f"efergy_h3_{sid}",
                "value": value_deciwatts,
                "rssi": None,
                "hub_version": "h3",
                "firmware_version": firmware_version,
                "timestamp": base_timestamp + offset_seconds,
            }
        )

    if cursor < len(post_data_bytes) and len(post_data_bytes) - cursor < FRAME_SIZE:
        logging.debug(
            "Ignoring %d trailing bytes at end of h3bulk payload",
            len(post_data_bytes) - cursor,
        )

    return results
