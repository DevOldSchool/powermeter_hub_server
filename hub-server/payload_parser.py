import json
import logging
from typing import List, Optional

def parse_sensor_line(line: str, hub_version: str, firmware_version: str) -> Optional[dict]:
    """
    Parses a single line of sensor data.
    
    Returns a dictionary with sensor data or None if the line should be skipped or is malformed.
    """
    if not line:
        return None

    try:
        data = line.split("|")
        if len(data) < 4:
            logging.warning(f"Malformed line, skipping: '{line}'")
            return None

        sid = data[0]
        if sid == "0":  # Skip hub status lines
            return None

        data_type = data[2].upper()

        rssi_val = None
        # --- EFMS1 Multi-sensor processing ---
        if data_type.startswith("EFMS"):
            # M = motion
            # T = temperature
            # L = light
            raw_block = data[3]  # Example: "M,64.00&T,0.00&L,0.00"

            # Some packets include RSSI after an additional pipe
            if len(data) >= 5:
                try:
                    rssi_val = float(data[4])
                except ValueError:
                    pass

            metrics_list = []
            # Split metrics by "&" and log
            metrics = raw_block.split("&")
            for metric in metrics:
                try:
                    key, val = metric.split(",", 1)
                    key = key.strip().upper()
                    num = float(val)
                    metrics_list.append((key, num))
                    logging.debug(f"[EFMS1] SID={sid}, Metric={key}, Value={num}")
                except Exception as e:
                    logging.warning(f"[EFMS1] Failed to parse metric '{metric}': {e}")

            if rssi_val is not None:
                logging.debug(f"[EFMS1] SID={sid}, RSSI={rssi_val}")
            
            return {
                "type": "EFMS",
                "sid": sid,
                "metrics": metrics_list,
                "rssi": rssi_val
            }

        if hub_version == 'h1':
            # V1: *Raw sensor* values, converted to kilowatts during aggregation
            # Data format: MAC|counter|v1.0.1|{"data":[[sensor_id,"mA","E1",milliamps,0,0,65535]]}|hash

            # MAC address = sensor ID for V1
            sid = data[0]
            firmware_version = data[1]
            jdata = json.loads(data[3])
            value = float(jdata['data'][0][3])
            label = f"efergy_{hub_version}_{sid}"
        else:
            # --- Normal CT sensor processing for v2/v3 ---
            # V2: *Raw sensor* values, converted to kilowatts during aggregation
            # V3: *Pre-scaled* values, converted to kilowatts during aggregation
            port_and_value = data[3]
            value_str = port_and_value.split(",")[1]
            value = float(value_str)
            sid = data[0]
            label = f"efergy_{hub_version}_{sid}"
            
            # H3 can include RSSI
            if len(data) >= 5:
                try:
                    rssi_val = float(data[4])
                except ValueError:
                    pass

        return {
            "type": "CT",
            "sid": sid,
            "label": label,
            "value": value,
            "rssi": rssi_val,
            "hub_version": hub_version,
            "firmware_version": firmware_version,
        }

    except (IndexError, ValueError, TypeError, json.JSONDecodeError) as e:
        logging.warning(f"Failed to parse line '{line}': {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error processing line '{line}': {e}")
        return None


def parse_sensor_payload(post_data_bytes: bytes, hub_version: str, firmware_version: str) -> List[dict]:
    """
    Parses a full POST body containing sensor data.
    """
    try:
        http_data_str = post_data_bytes.decode("utf-8")
        sensor_lines = http_data_str.split("\r\n")
    except UnicodeDecodeError as e:
        logging.error(f"Failed to decode POST body: {e}")
        return []

    results = []
    for line in sensor_lines:
        parsed = parse_sensor_line(line, hub_version, firmware_version)
        if parsed:
            results.append(parsed)

    return results
