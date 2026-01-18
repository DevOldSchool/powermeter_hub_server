# Efergy Hub Local Data Logger

This project provides a local emulation server for legacy Efergy Engage hubs (v1, v2, and v3). 
It allows you to intercept and log your home's energy data to a local SQLite database, completely bypassing the 
decommissioned Efergy cloud servers.

This is designed for anyone who wants to keep their devices from becoming e-waste.

## How it Works

The Efergy Hub is hard-coded to send its data to `sensornet.info` over HTTPS. 
Unfortunately, these old devices use the deprecated SSLv3 protocol, which modern web servers and Python libraries will 
not accept.

This project solves the problem with a two-service system managed by Docker Compose:

1. **`legacy-nginx` Service**: A custom-built Nginx server acts as a reverse proxy. It uses an old version of OpenSSL (1.0.2u) specifically compiled to accept the hub's SSLv3 connection. It then terminates the SSL and forwards the decrypted HTTP traffic to the Python application.
2. **`hub-server` Service**: A lightweight Python 3 server (`hub_server.py`) that listens for the forwarded requests. It receives the plain HTTP request from the Nginx proxy, emulates the Efergy API, and logs the data to a SQLite database (`readings.db`) using the `db.py` script.


## Setup with Docker Compose

### 1. Generate SSL Certificates

The `legacy-nginx` service requires SSL certificates to run. A helper script is provided to generate self-signed certificates.

1. Make the script executable:
```shell
chmod +x ./generate-certs.sh
```
2. Run the script from the project's root directory:

```shell
./generate-certs.sh
```
This will create `server.key` and `server.crt` inside the `legacy-nginx` directory, where the `docker-compose.yml` file 
expects to find them.

### 2. Configuration

The `hub-server` can be configured using environment variables in the `docker-compose.yml` file.

#### Identifying your Hub Version

Efergy Hubs (H1, H2, and H3) send data in different formats and to different endpoints. To ensure the `POWER_FACTOR` and data parsing are correct, you need to identify your hub version.

The `hub-server` will automatically log the detected version at the `INFO` level when it receives the first packet from your device.

1.  **Check the logs**: View the logs of the `hub-server` container as the device sends data (usually every 6-30 seconds):
    ```shell
    docker logs -f hub-server
    ```
2.  **Look for the detection message**:
    - `Detected Efergy Hub version: H1`
    - `Detected Efergy Hub version: H2`
    - `Detected Efergy Hub version: H3`

3.  **Update Configuration**: Once identified, update your `docker-compose.yml` with the appropriate `POWER_FACTOR`:
    - **H1 / H2**: `0.6`
    - **H3**: `1.0`

*Note: If you don't see the detection message, you can temporarily set `LOG_LEVEL: DEBUG` in `docker-compose.yml` to see all incoming requests and identify the endpoint (`/recjson` = H1, `/h2` = H2, `/h3` = H3).*

#### Environment Variables

| Variable                   | Description                                               | Default                     |
|----------------------------|-----------------------------------------------------------|-----------------------------|
| `TZ`                       | Timezone (e.g., `Australia/Brisbane`)                     | `Australia/Brisbane`        |
| `LOG_LEVEL`                | Logging verbosity (`DEBUG`, `INFO`, `WARN`, `ERROR`)      | `INFO`                      |
| `TELEMETRY_ENABLED`        | Record unknown packets to help aid reverse engineering.   | `true`                      |
| `MAINS_VOLTAGE`            | Local mains voltage (e.g., `230` for AU/UK, `120` for US) | `230`                       |
| `POWER_FACTOR`             | Power factor (H1/H2 use `0.6`, H3 uses `1.0`)             | `0.6`                       |
| `HISTORY_RETENTION_MONTHS` | How many months of data to keep (`0` = keep everything)   | `0`                         |
| `MQTT_ENABLED`             | Enable or disable MQTT publishing (`true`/`false`)        | `false`                     |
| `MQTT_BROKER`              | IP address or hostname of your MQTT broker                | `10.0.0.220`                |
| `MQTT_PORT`                | Port for your MQTT broker                                 | `1883`                      |
| `MQTT_USER`                | Username for MQTT broker                                  | `None`                      |
| `MQTT_PASS`                | Password for MQTT broker                                  | `None`                      |
| `HA_DISCOVERY`             | Enable Home Assistant MQTT Discovery (`true`/`false`)     | `false`                     |
| `ENERGY_MONTHLY_RESET`     | Reset cumulative energy in HA each month (`true`/`false`) | `false`                     |
| `DEVICE_URL`               | Link to device management (e.g., Portainer or NAS UI)     | `.../powermeter_hub_server` |

### 3. Run the Services

With the certificates in place, you can start both services using Docker Compose.

```shell
# Start the containers in detached mode
docker-compose up -d
```

This will:
* Start both containers. The `legacy-nginx` service is exposed on port `443`.
* Automatically create the SQLite database on the first run and mount the data directory for persistence.

### 3. Redirect the Efergy Hub

Finally, you must trick your Efergy Hub into sending data to your new server instead of `sensornet.info`.
The easiest way to do this is with DNS spoofing on your router (e.g., using `dnsmasq`, `Pi-hole`, or similar):

Create DNS entries that map your hub's specific domain(s) to the local IP address of the machine running your Docker container 
(e.g., `10.0.0.213`).

**Domain patterns by hub version:**
- **V1 hubs:** `[MAC].sensornet.info` and `[MAC].keys.sensornet.info` (e.g., `aa.bb.cc.dddddd.sensornet.info`)
- **V2/V3 hubs:** `[MAC].[h2/h3].sensornet.info` (e.g., `41.0a.04.001ec0.h2.sensornet.info`)

Once the hub is rebooted, it will contact `sensornet.info`, be directed to your `legacy-nginx` proxy, and your 
`hub-server` should start logging data to `readings.db`.

#### Pi-hole example

Navigate to Settings -> Local DNS Records and add entries for your hub:

**For v2/v3 hubs:**

| Domain                              | IP          |
|-------------------------------------|-------------|
| [device mac].[h2/h3].sensornet.info | [server ip] |
| 41.0a.04.001ec0.h2.sensornet.info   | 10.0.0.213  |

**For v1 hubs:**

| Domain                              | IP          |
|-------------------------------------|-------------|
| [device mac].sensornet.info         | [server ip] |
| [device mac].keys.sensornet.info    | [server ip] |
| aa.bb.cc.dddddd.sensornet.info      | 10.0.0.213  |
| aa.bb.cc.dddddd.keys.sensornet.info | 10.0.0.213  |

#### pfSense example

Navigate to Services -> DNS Resolver -> Custom Options and add entries for your hub:

**For all hubs (wildcard approach):**
```
server:
    local-zone: "sensornet.info" redirect
    local-data: "sensornet.info 86400 IN A 10.0.0.213"
```

**Or for specific domains:**
```
server:
    # V2/V3 hubs
    local-data: "41.0a.04.001ec0.h2.sensornet.info 86400 IN A 10.0.0.213"
    # V1 hubs
    local-data: "aa.bb.cc.dddddd.sensornet.info 86400 IN A 10.0.0.213"
    local-data: "aa.bb.cc.dddddd.keys.sensornet.info 86400 IN A 10.0.0.213"
``` 

## Data Formats and Units

**MQTT payloads:**
- **Power**: Raw sensor values (h1/h2: milliamps; h3: deciwatts). 
  - See below for conversion to Watts.
- **Energy**: Kilowatt-hours (kWh)

**For Home Assistant users**: When MQTT discovery is *enabled*, Home Assistant automatically converts Power readings to watts using the `value_template` included in discovery messages.

**For other MQTT consumers**: You must apply the conversion yourself. Formulas are in `config.py`.

## Home Assistant Integration

### Home Assistant Operating System hosted

If your Efergy Hub server is running on HA OS, you can integrate the readings into Home Assistant via [MQTT](https://www.home-assistant.io/integrations/mqtt/).

1. **Configure Environment Variables** for MQTT

Configure your environment variables in the `docker-compose.yml` file as described in the [Configuration](#configuration) section. 
For Home Assistant with MQTT, you should at least set:
```yaml
MQTT_ENABLED: true
MQTT_BROKER: homeassistant.local
MQTT_USER: mqtt-broker-username-here
MQTT_PASS: your-password-here
HA_DISCOVERY: true
```

2. **Home Assistant Auto-Discovery** 

With `HA_DISCOVERY=true`, the hub-server will automatically publish Home Assistant MQTT discovery payloads. This creates two sensors per Efergy device:

| Sensor                                 | Topic                                   | Unit | Device Class | State Class      |
|----------------------------------------|-----------------------------------------|------|--------------|------------------|
| `sensor.efergy_hub_power_<sid>`        | `home/efergy/efergy_h<X>_<SID>/power`   | W    | power        | measurement      |
| `sensor.efergy_hub_energy_consumption` | `home/efergy/energy_consumption/energy` | kWh  | energy       | total_increasing |

> **Note**: 
> MQTT payloads for power are raw values, but Home Assistant applies the necessary conversion to Watts automatically. See the [Data Formats and Units](#data-formats-and-units) section for details.

Home Assistant will pick up these sensors automatically, making them available for dashboards, automations, and the Energy Dashboard.

3. Add Sensors to Energy Dashboard

Once discovered, the `sensor.efergy_hub_energy_consumption` sensor can be added to Home Assistant’s Energy Dashboard under Grid Consumption, allowing you to track daily, weekly, and monthly usage.


### Container hosted

You can integrate your local energy data into Home Assistant using the [SQL Sensor](https://www.home-assistant.io/integrations/sql/) 
integration. 
This allows Home Assistant to directly query the `readings.db` file.

The provided `sensors.yaml` file is a configuration snippet you can add to your Home Assistant setup.

1. **Ensure Home Assistant can access the database.** Make sure your `readings.db` file is located somewhere [Home Assistant](https://www.home-assistant.io/) can read it (e.g., in your /config directory).
2. **Add the SQL integration** to your `configuration.yaml` if you haven't already.
3. **Add the sensor configuration.** You can copy the contents of `sensors.yaml` into your Home Assistant's `configuration.yaml` (under a sql: key) or, if you have a split configuration, !include it.

`configuration.yaml` example:
```yaml

# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml
sql: !include sensors.yaml
```

4. **Update the** `db_url` in `sensors.yaml`.
5. **Restart Home Assistant**.

You will now have two sensors:
* `sensor.efergy_hub_power_<sid>`: The instantaneous power reading in W.
* `sensor.efergy_hub_energy_consumption`: A running total of energy consumed in kWh, which can be added directly to your Home Assistant Energy Dashboard.


### Other

* [QNAP NAS](https://github.com/DevOldSchool/powermeter_hub_server/wiki/QNAP-NAS-Setup)
* [Synology NAS](https://github.com/DevOldSchool/powermeter_hub_server/wiki/Synology-NAS-Setup)

## Efergy Data Format

Documentation about the known hub payload formats and data structures:
- [Hub v1 Data Format](https://github.com/DevOldSchool/powermeter_hub_server/wiki/Hub-V1-Data-Format)
- [Hub v2/v3 Data Format](https://github.com/DevOldSchool/powermeter_hub_server/wiki/Hub-v2-v3-Data-Format)
