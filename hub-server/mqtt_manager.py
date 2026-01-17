import json
import logging
import time
import paho.mqtt.client as mqtt
from __version__ import __version__
from config import (
    MQTT_ENABLED, MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASS,
    MQTT_BASE_TOPIC, HA_DISCOVERY, HA_DISCOVERY_PREFIX,
    POWER_NAME, POWER_ICON, POWER_DEVICE_CLASS, POWER_STATE_CLASS,
    POWER_UNIT_OF_MEASUREMENT_H1, POWER_VALUE_TEMPLATE_H1,
    POWER_UNIT_OF_MEASUREMENT_H2, POWER_VALUE_TEMPLATE_H2,
    POWER_UNIT_OF_MEASUREMENT_H3, POWER_VALUE_TEMPLATE_H3,
    ENERGY_NAME, ENERGY_ICON, ENERGY_DEVICE_CLASS, ENERGY_STATE_CLASS,
    ENERGY_UNIT_OF_MEASUREMENT, ENERGY_VALUE_TEMPLATE,
    DEVICE_NAME, DEVICE_MODEL, DEVICE_IDENTIFIERS, DEVICE_MANUFACTURER,
    DEVICE_URL
)

ENERGY_SENSOR_LABEL = "energy_consumption"

def get_topic(label, sensor_type="power"):
    if sensor_type == "power":
        return f"{MQTT_BASE_TOPIC}/{label}/power"
    else:
        return f"{MQTT_BASE_TOPIC}/{label}/energy"



class MQTTManager:
    def __init__(self, max_retries: int = 10, retry_interval: int = 5):
        self.enabled = MQTT_ENABLED
        self.discovery_enabled = HA_DISCOVERY
        self.discovery_sent = set()
        self.max_retries = max_retries
        self.retry_interval = retry_interval
        self.connected = False
        self.hub_version: str | None = None

        if not self.enabled:
            logging.debug("MQTT disabled via config.")
            return

        logging.debug("Initializing MQTT client...")
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)

        # Configure auto-reconnect delays
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)

        # Set callback to log connection events
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        # Attempt initial connection with retries
        self._connect_with_retry()

        # Start network loop in background
        self.client.loop_start()


    def _connect_with_retry(self):
        retries = 0
        while retries < self.max_retries:
            try:
                self.client.connect(MQTT_BROKER, MQTT_PORT)
                logging.debug(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
                return
            except Exception as e:
                retries += 1
                logging.warning(f"MQTT connection attempt {retries} failed: {e}")
                time.sleep(self.retry_interval)
        logging.error("Failed to connect to MQTT broker after multiple attempts.")
        self.enabled = False


    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self.connected = True
            logging.debug("MQTT connected successfully.")
        else:
            logging.warning(f"MQTT connection returned code {reason_code}")


    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        if reason_code != 0:
            logging.warning(f"Unexpected MQTT disconnect (rc={reason_code}). Will auto-reconnect.")


    # Generic publishing
    def publish(self, topic: str, payload: dict, retain: bool = False):
        if not self.enabled:
            return

        # Wait until MQTT is connected
        wait_count = 0
        while not self.connected and wait_count < 50:
            logging.debug(f"Waiting for MQTT connection to publish {topic}...")
            time.sleep(0.1)
            wait_count += 1

        if not self.connected:
            logging.warning(f"MQTT not connected, skipping publish: {topic}")
            return

        try:
            json_payload = json.dumps(payload)
            self.client.publish(topic, json_payload, retain=retain)
            logging.debug(f"MQTT published to {topic}: {json_payload[:400]}")
        except Exception as e:
            logging.error(f"MQTT publish failed: {topic} — {e}")


    def publish_power_discovery(self, label: str, sid: str, topic: str, hub_version: str):
        if not self.enabled or not HA_DISCOVERY:
            return
        if self.hub_version is None:
            logging.warning("Energy discovery attempted without hub_version – skipped")
            return

        config_topic = f"{HA_DISCOVERY_PREFIX}/sensor/{label}/config"

        if hub_version == "h1" or hub_version.startswith("v1"):
            # V1 hub: value is already in watts, convert to kW
            unit_of_measurement = POWER_UNIT_OF_MEASUREMENT_H1
            value_template = POWER_VALUE_TEMPLATE_H1
        elif hub_version == "h2":
            # value is in hundredths of an amp (A * 100)
            unit_of_measurement = POWER_UNIT_OF_MEASUREMENT_H2
            value_template = POWER_VALUE_TEMPLATE_H2
        elif hub_version == "h3":
            # value is in deciwatts (W * 10)
            unit_of_measurement = POWER_UNIT_OF_MEASUREMENT_H3
            value_template = POWER_VALUE_TEMPLATE_H3
        else:
            unit_of_measurement = "W"
            value_template = "{{ (value_json.value | float) }}"

        payload = {
            "name": f"{POWER_NAME} - {sid}",
            "state_topic": topic,
            "unit_of_measurement": unit_of_measurement,
            "value_template": value_template,
            "unique_id": f"{label}_power",
            "icon": POWER_ICON,
            "device_class": POWER_DEVICE_CLASS,
            "state_class": POWER_STATE_CLASS,
            "device": {
                "name": DEVICE_NAME,
                "identifiers": DEVICE_IDENTIFIERS,
                "manufacturer": DEVICE_MANUFACTURER,
                "model": DEVICE_MODEL,
                "hw_version": f"{hub_version}",
                "configuration_url": DEVICE_URL
            }
        }

        self.publish(config_topic, payload, retain=True)
        self.discovery_sent.add(label)


    def publish_energy_discovery(self, topic: str):
        """
        Home Assistant discovery for energy sensor.
        """
        if not self.enabled or not HA_DISCOVERY:
            return

        config_topic = f"{HA_DISCOVERY_PREFIX}/sensor/{ENERGY_SENSOR_LABEL}/config"

        payload = {
            "name": ENERGY_NAME,
            "state_topic": topic,
            "unit_of_measurement": ENERGY_UNIT_OF_MEASUREMENT,
            "value_template": ENERGY_VALUE_TEMPLATE,
            "unique_id": ENERGY_SENSOR_LABEL,
            "icon": ENERGY_ICON,
            "device_class": ENERGY_DEVICE_CLASS,
            "state_class": ENERGY_STATE_CLASS,
            "device": {
                "name": DEVICE_NAME,
                "identifiers": DEVICE_IDENTIFIERS,
                "manufacturer": DEVICE_MANUFACTURER,
                "model": DEVICE_MODEL,
                "configuration_url": DEVICE_URL
            }
        }

        self.publish(config_topic, payload, retain=True)
        self.discovery_sent.add(ENERGY_SENSOR_LABEL)


    # Publishes reading AND automatically discovery if needed
    def publish_power(self, label: str, sid: str, hub_version: str, value: float):
        if not self.enabled:
            return

        # Store hub version once
        if self.hub_version is None:
            self.hub_version = hub_version
            logging.info(f"Detected hub version: {hub_version}")

        logging.debug(f"Publishing power for {label} with value {value}")
        topic = get_topic(label, sensor_type="power")

        # Publish actual reading
        self.publish(topic, {"value": value})

        # Publish discovery ONLY once
        if self.discovery_enabled and label not in self.discovery_sent:
            self.publish_power_discovery(label, sid, topic, hub_version)
            self.discovery_sent.add(label)


    def publish_energy(self, value_kwh: float):
        """
        Publish energy consumption (kWh).
        """
        if not self.enabled:
            return

        logging.debug(f"Publishing energy for {ENERGY_SENSOR_LABEL} with value {value_kwh}")
        topic = get_topic(ENERGY_SENSOR_LABEL, sensor_type="energy")

        # Publish energy consumption
        self.publish(topic, {"value": value_kwh})

        # Publish discovery ONLY once
        if self.discovery_enabled and ENERGY_SENSOR_LABEL not in self.discovery_sent:
            self.publish_energy_discovery(topic)


    def publish_startup_discovery(self, labels):
        """
        Publish HA discovery for all stored sensors at startup.
        """
        if not self.enabled or not HA_DISCOVERY:
            return

        logging.debug(f"Publishing discovery info for {len(labels)} stored sensors...")

        for label in labels:
            parts = label.split("_")
            if len(parts) < 3:
                continue

            # Power topic

            # Label format for all versions: efergy_hX_SID
            # V1: efergy_h1_0004A34DAF3C (SID is MAC address)
            # V2: efergy_h2_123456 (SID is sensor ID)
            # V3: efergy_h3_123456 (SID is sensor ID)
            hub_version = parts[1]
            sid = parts[2]

            power_topic = get_topic(label, sensor_type="power")
            self.publish_power_discovery(label, sid, power_topic, hub_version)

        # Energy topic
        energy_topic = get_topic(ENERGY_SENSOR_LABEL, sensor_type="energy")
        self.publish_energy_discovery(energy_topic)
