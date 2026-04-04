import pytest

from bulk_parser import parse_h3bulk_payload


def test_parse_h3bulk_payload():
    payload = bytes.fromhex(
        """
        C7 B3 76 69 2C 16 0D 59 12 0D 7A 16 0D 27 12 0D
        00 00 00 24 00 00 DD F3 36 44 6E 26 00 00 A6 81
        02 45 94 20 00 3B B3 6D 01 45 C1 22 00 3B AC 2E
        36 45 B2 24 00 3B AC EA 34 44 6D 26 00 3B B0 95
        FD 44 E7 20 00 77 6B 1C 02 45 65 22 00 77 60 FF
        """.replace("\n", " ").strip()
    )

    result = parse_h3bulk_payload(payload, firmware_version="3.7.1")

    assert len(result) == 7

    assert result[0]["type"] == "CT"
    assert result[0]["sid"] == "857644"
    assert result[0]["label"] == "efergy_h3_857644"
    assert result[0]["timestamp"] == 1769386951
    assert result[0]["value"] == pytest.approx(7286.0)

    assert result[4]["sid"] == "857722"
    assert result[4]["timestamp"] == 1769387010
    assert result[4]["value"] == pytest.approx(7206.0)

    assert result[-1]["sid"] == "857644"
    assert result[-1]["timestamp"] == 1769387070
    assert result[-1]["value"] == pytest.approx(20821.5)


def test_parse_h3bulk_payload_rejects_short_payload():
    assert parse_h3bulk_payload(b"\x00\x01\x02", firmware_version="3.7.1") == []


def test_parse_h3bulk_payload_treats_denormal_values_as_zero():
    payload = bytes.fromhex(
        """
        21 B3 AE 69 D0 51 0C AB 60 0C 4A 63 0C 73 5F 0C
        00 62 0C 20 00 00 04 76 05 46 E5 22 00 00 00 00
        00 00 22 20 00 3B 72 1A F4 45 20 22 00 3B 00 00
        00 00 5D 20 00 4C C8 58 EB 45 BC 22 00 4C 00 00
        00 00 6E FF FF FF FF FF FF FF FF FF FF FF FF FF
        FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF
        """.replace("\n", " ").strip()
    )

    result = parse_h3bulk_payload(payload, firmware_version="3.7.1")

    assert len(result) == 6
    assert result[1]["sid"] == "811179"
    assert result[1]["value"] == 0.0
    assert result[3]["sid"] == "811179"
    assert result[3]["value"] == 0.0
    assert result[5]["sid"] == "811179"
    assert result[5]["value"] == 0.0
