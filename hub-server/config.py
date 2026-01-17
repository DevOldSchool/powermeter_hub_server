import os

# Hub server config
SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))
MAINS_VOLTAGE = int(os.getenv("MAINS_VOLTAGE", "230"))
POWER_FACTOR = float(os.getenv("POWER_FACTOR", "0.6"))

# Logging level, values are DEBUG, INFO, WARN, ERROR, CRITICAL
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# SQL timeout in seconds
SQLITE_TIMEOUT = float(os.getenv("SQLITE_TIMEOUT", "5.0"))
SQLITE_RETRIES = int(os.getenv("SQLITE_RETRIES", "5"))
SQLITE_RETRY_DELAY = float(os.getenv("SQLITE_RETRY_DELAY", "0.2"))

# Enable or disable MQTT
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "false").lower() in ("true", "1", "yes", "on")

# MQTT configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "10.0.0.220")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", None)
MQTT_PASS = os.getenv("MQTT_PASS", None)
MQTT_BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", "home/efergy")

# Home Assistant
HA_DISCOVERY = os.getenv("HA_DISCOVERY", "false").lower() in ("true", "1", "yes", "on")
HA_DISCOVERY_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant")

POWER_NAME = os.getenv("POWER_NAME", "Power")
POWER_ICON = os.getenv("POWER_ICON", "mdi:flash")
POWER_DEVICE_CLASS = os.getenv("POWER_DEVICE_CLASS", "power")
POWER_STATE_CLASS = os.getenv("POWER_STATE_CLASS", "measurement")

# Formulas
# AC single phase milliamps to watts calculation P(W) = (PF × V(V) × I(mA)) / 1000

POWER_VALUE_TEMPLATE_H1_RAW = os.getenv("POWER_VALUE_TEMPLATE_H1_RAW", "{{ (__POWER_FACTOR__ * __MAINS_VOLTAGE__ * (value_json.value | float)) / 1000 }}")
POWER_VALUE_TEMPLATE_H1 = POWER_VALUE_TEMPLATE_H1_RAW.replace("__MAINS_VOLTAGE__", str(MAINS_VOLTAGE)).replace("__POWER_FACTOR__", str(POWER_FACTOR))
POWER_UNIT_OF_MEASUREMENT_H1 = os.getenv("POWER_UNIT_OF_MEASUREMENT_H1", "W")

POWER_VALUE_TEMPLATE_H2_RAW = os.getenv("POWER_VALUE_TEMPLATE_H2_RAW", "{{ (__POWER_FACTOR__ * __MAINS_VOLTAGE__ * (value_json.value | float)) / 1000 }}")
POWER_VALUE_TEMPLATE_H2 = POWER_VALUE_TEMPLATE_H2_RAW.replace("__MAINS_VOLTAGE__", str(MAINS_VOLTAGE)).replace("__POWER_FACTOR__", str(POWER_FACTOR))
POWER_UNIT_OF_MEASUREMENT_H2 = os.getenv("POWER_UNIT_OF_MEASUREMENT_H2", "W")

POWER_VALUE_TEMPLATE_H3 = os.getenv("POWER_VALUE_TEMPLATE_H3", "{{ (value_json.value | float) / 10 }}")
POWER_UNIT_OF_MEASUREMENT_H3 = os.getenv("POWER_UNIT_OF_MEASUREMENT_H3", "W")

ENERGY_NAME = os.getenv("ENERGY_NAME", "Energy consumption")
ENERGY_ICON = os.getenv("ENERGY_ICON", "mdi:lightning-bolt")
ENERGY_DEVICE_CLASS = os.getenv("ENERGY_DEVICE_CLASS", "energy")
ENERGY_STATE_CLASS = os.getenv("ENERGY_STATE_CLASS", "total_increasing")

ENERGY_VALUE_TEMPLATE = os.getenv("ENERGY_VALUE_TEMPLATE", "{{ value_json.value }}")
ENERGY_UNIT_OF_MEASUREMENT = os.getenv("ENERGY_UNIT_OF_MEASUREMENT", "kWh")

ENERGY_MONTHLY_RESET = os.getenv("ENERGY_MONTHLY_RESET", "false").lower() in ("true", "1", "yes", "on")

# History retention in months (0 means keep everything)
HISTORY_RETENTION_MONTHS = int(os.getenv("HISTORY_RETENTION_MONTHS", "0"))

DEVICE_NAME = os.getenv("DEVICE_NAME", "Efergy Hub")
DEVICE_IDENTIFIERS = os.getenv("DEVICE_IDENTIFIERS", ["efergy"])
DEVICE_MANUFACTURER = os.getenv("DEVICE_MANUFACTURER", "Efergy")
DEVICE_MODEL = os.getenv("DEVICE_MODEL", "Hub")
DEVICE_URL = os.getenv("DEVICE_URL", "https://github.com/DevOldSchool/powermeter_hub_server")
