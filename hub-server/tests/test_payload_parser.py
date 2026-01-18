from payload_parser import parse_sensor_line


def test_h1_payload():
    line = 'MAC123|694851F9|v1.0.1|{"data":[[610965,"mA","E1",33314,0,0,65535]]}|39ef0bdc14b52df375b79555f059b52f'
    hub_version = "h1"
    firmware_version = "2.3.7"

    result = parse_sensor_line(line, hub_version, firmware_version)

    assert result is not None
    assert result["type"] == "CT"
    assert result["sid"] == "MAC123"
    assert result["label"] == "efergy_h1_MAC123"
    assert result["value"] == 33314.0


def test_h2_single_sensor_payload():
    line = "741459|1|EFCT|P1,2479.98"
    hub_version = "h2"
    firmware_version = "2.3.7"

    result = parse_sensor_line(line, hub_version, firmware_version)

    assert result is not None
    assert result["type"] == "CT"
    assert result["sid"] == "741459"
    assert result["label"] == "efergy_h2_741459"
    assert result["value"] == 2479.98
    assert result["hub_version"] == "h2"


def test_h2_multi_sensor_example():
    line = "747952|0|EFMS1|M,96.00&T,0.00&L,0.00|-67"
    hub_version = "h2"
    firmware_version = "2.3.7"

    result = parse_sensor_line(line, hub_version, firmware_version)

    assert result is not None
    assert result["type"] == "EFMS"
    assert result["sid"] == "747952"
    assert result["rssi"] == -67.0
    assert ("M", 96.00) in result["metrics"]


def test_h3_example():
    line = "815751|1|EFCT|P1,391.86|-66"
    hub_version = "h3"
    firmware_version = "2.3.7"

    result = parse_sensor_line(line, hub_version, firmware_version)

    assert result is not None
    assert result["type"] == "CT"
    assert result["sid"] == "815751"
    assert result["value"] == 391.86
    assert result["rssi"] == -66.0


def test_efms_payload():
    line = "741459|1|EFMS|M,64.00&T,22.50&L,100.00|85"
    hub_version = "h2"
    firmware_version = "2.3.7"

    result = parse_sensor_line(line, hub_version, firmware_version)

    assert result is not None
    assert result["type"] == "EFMS"
    assert result["sid"] == "741459"
    assert len(result["metrics"]) == 3
    assert ("M", 64.00) in result["metrics"]
    assert ("T", 22.50) in result["metrics"]
    assert ("L", 100.00) in result["metrics"]
    assert result["rssi"] == 85.0


def test_hub_status_line():
    line = "0|1|STATUS|OK"
    hub_version = "h2"
    firmware_version = "2.3.7"

    result = parse_sensor_line(line, hub_version, firmware_version)

    assert result is None
