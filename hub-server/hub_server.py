"""
A fake Efergy sensor data server, updated for Python 3.

This server emulates the sensornet.info API endpoints for an
Efergy hub, logging incoming sensor data to a sqlite database.
"""
import logging
import math
import socket
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Type
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from database import Database
from mqtt_manager import MQTTManager
from aggregator import Aggregator
from payload_parser import parse_sensor_payload
from bulk_parser import parse_h3bulk_payload
from __version__ import __version__
from config import (
    SERVER_PORT, LOG_LEVEL, MQTT_ENABLED, HA_DISCOVERY, ENERGY_MONTHLY_RESET, HISTORY_RETENTION_MONTHS, SQLITE_TIMEOUT,
    SQLITE_RETRIES, SQLITE_RETRY_DELAY, POWER_VALUE_TEMPLATE_H1, POWER_UNIT_OF_MEASUREMENT_H1, POWER_VALUE_TEMPLATE_H2,
    POWER_UNIT_OF_MEASUREMENT_H2, POWER_VALUE_TEMPLATE_H3, POWER_UNIT_OF_MEASUREMENT_H3, ENERGY_VALUE_TEMPLATE,
    ENERGY_UNIT_OF_MEASUREMENT
)

INT32_MAX = 2_147_483_647


def is_valid_power_reading(value: float) -> bool:
    """Reject non-finite readings and the INT32_MAX emitted by faulty hubs."""
    return math.isfinite(value) and value < INT32_MAX


class EfergyHTTPServer(HTTPServer):
    """
    A custom HTTPServer subclass that holds the database instance.
    This allows the request handler to access the database instance
    via `self.server.database`.
    """
    def __init__(self,
                 server_address: tuple[str, int],
                 request_handler_class: Type[SimpleHTTPRequestHandler],
                 database: Database,
                 mqtt_manager: MQTTManager,
                 bind_and_activate: bool = True):

        # Store the database instance *before* calling super_init
        # so it's available if the handler needs it during init.
        self.database = database
        self.mqtt_manager = mqtt_manager
        self.published_discovery = set()
        self.detected_versions = set()
        super().__init__(server_address, request_handler_class, bind_and_activate)


class FakeEfergyServer(SimpleHTTPRequestHandler):
    """
    Pretends to be a sensornet.info server.
    It accesses the database instance via `self.server.database`.

    Note: self.server will be an instance of EfergyHTTPServer.
    """
    protocol_version = "HTTP/1.1"
    server: "EfergyHTTPServer"

    def log_request_info(self):
        """Helper to log request details using f-strings."""
        parsed_url = urlparse(self.path)
        query = parse_qs(parsed_url.query)
        client_ip, client_port = self.client_address

        logging.debug("=" * 80)
        logging.debug(f">>> REQUEST: {self.command} {self.path}")
        logging.debug(f">>> Query params: {query}")
        logging.debug(f">>> Headers: {dict(self.headers)}")
        logging.debug(f">>> Client: {client_ip}:{client_port}")


    def _send_response(self, code: int, content_bytes: bytes, content_type: str = "text/html; charset=UTF-8"):
        """Helper to send a complete response."""
        try:
            response_preview = content_bytes.decode('utf-8', 'ignore')[:200] if content_bytes else ''
            logging.debug(f"<<< RESPONSE: {code} | Length: {len(content_bytes)} | Content: {response_preview!r}")

            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content_bytes)))
            self.end_headers()

            try:
                self.wfile.write(content_bytes)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, socket.error) as e:
                logging.debug(
                    f"Client disconnected while sending response "
                    f"(BrokenPipe): {e} — path: {self.path}"
                )
                return

        except Exception as e:
            logging.error(f"Failed during response send: {e}")


    def _handle_unknown_packet(self, post_data_bytes: bytes = None):
        try:
            parsed_url = urlparse(self.path)
            query = parse_qs(parsed_url.query)
            method = self.command
            path = self.path
            content_length = int(self.headers.get("Content-Length", 0))
            content_type = self.headers.get("Content-Type", "")

            if post_data_bytes is None and content_length > 0:
                post_data_bytes = self.rfile.read(content_length)

            logging.warning("========== UNKNOWN PACKET ==========")
            logging.warning("Method: %s", method)
            logging.warning("Raw path: %s", path)
            logging.warning("Path: %s", parsed_url.path)
            logging.warning("Query: %s", query)
            logging.warning("Content-Type: %s", content_type)
            logging.warning("Content-Length: %d", content_length)
            logging.warning("Headers: %s", dict(self.headers))

            if not post_data_bytes:
                logging.warning("No request body present")
            else:
                body_utf8 = post_data_bytes.decode("utf-8", "ignore")
                hex_lines = []

                for i in range(0, len(post_data_bytes), 16):
                    chunk = post_data_bytes[i:i + 16]
                    hex_bytes = " ".join(f"{b:02X}" for b in chunk)
                    ascii_bytes = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
                    hex_lines.append(f"{i:04X}  {hex_bytes:<48}  {ascii_bytes}")

                body_hex = "\n".join(hex_lines)
                logging.warning("Payload UTF8:\n%s", body_utf8)
                logging.warning("Payload HEX:\n%s", body_hex)

            logging.warning("====================================")
        except Exception:
            logging.exception("Error in unknown HTTP handler")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")


    def do_GET(self):
        """Handles GET requests for key checking."""
        try:
            self.log_request_info()
            parsed_url = urlparse(self.path)

            code = 200

            if parsed_url.path == "/get_key.html":
                content_bytes = b"TT|a1bCDEFGHa1zZ\n"
            elif parsed_url.path == "/check_key.html":
                # Detect V1 hub by Host header pattern: [MAC].keys.sensornet.info
                # V2/V3 use: [MAC].[h2/h3].sensornet.info
                host_header = self.headers.get("Host", "")
                content_bytes = b"success"
                logging.debug(f"Key check from: {host_header}")
            else:
                code = 404
                content_bytes = b"Not Found"
                self._handle_unknown_packet()

            self._send_response(code, content_bytes)

        except Exception as e:
            logging.error(f"Exception in GET: {e}")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")


    def do_POST(self):
        """Handles POST requests with sensor data."""
        try:
            self.log_request_info()
            parsed_url = urlparse(self.path)

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                logging.warning("POST request with no content length or 0.")
                self._send_response(411, b"Content-Length required")
                return

            post_data_bytes = self.rfile.read(content_length)
            logging.debug(f">>> POST body: {post_data_bytes.decode('utf-8', 'ignore')}")

            firmware_version = self.headers.get("X-Version", "")

            db = getattr(self.server, "database", None)
            if not db:
                logging.error("Database not initialized on server instance.")
                self._send_response(500, b"Server Error: DB not configured")
                return

            content_type = self.headers.get("Content-Type", "")
            if content_type == "application/eh-ping":
                sensor_ids = post_data_bytes.decode("utf-8").strip().split("|")
                logging.debug(f"Received ping from sensors: {sensor_ids}")
            elif parsed_url.path in ["/h2", "/h3"]:
                hub_version = parsed_url.path.strip("/")
                self.process_sensor_data(post_data_bytes, hub_version, firmware_version, db)
            elif parsed_url.path == "/h3bulk":
                self.process_h3bulk_data(post_data_bytes, firmware_version, db)
            elif parsed_url.path == '/recjson':
                # v1 hub sends URL-encoded form data: json=<pipe-delimited-data>
                hub_version = 'h1'
                decoded_body = post_data_bytes.decode('utf-8', 'ignore')
                if decoded_body.startswith('json='):
                    # Extract the actual sensor data
                    sensor_data = decoded_body[5:]  # Skip 'json='
                    self.process_sensor_data(sensor_data.encode('utf-8'), hub_version, "", db)
                else:
                    logging.warning(f"Unexpected /recjson body format: {decoded_body[:100]}")
            else:
                self._handle_unknown_packet(post_data_bytes)

            self._send_response(200, b"success")

        except Exception as e:
            logging.error(f"Exception in POST: {e}")
            if not self.wfile.closed:
                self._send_response(500, b"Internal Server Error")


    def do_PUT(self):
        self._handle_unknown_packet()
        self._send_response(200, b"success")


    def do_DELETE(self):
        self._handle_unknown_packet()
        self._send_response(200, b"success")


    def do_OPTIONS(self):
        self._handle_unknown_packet()
        self._send_response(200, b"success")


    def do_PATCH(self):
        self._handle_unknown_packet()
        self._send_response(200, b"success")


    def do_HEAD(self):
        self._handle_unknown_packet()
        self._send_response(200, b"success")


    def do_TRACE(self):
        self._handle_unknown_packet()
        self._send_response(200, b"success")


    def do_CONNECT(self):
        self._handle_unknown_packet()
        self._send_response(200, b"success")


    def process_sensor_data(self, post_data_bytes: bytes, hub_version: str, firmware_version: str, database: Database):
        """Parses and logs sensor data from the POST body."""
        parsed_results = parse_sensor_payload(post_data_bytes, hub_version, firmware_version)
        self.process_parsed_results(parsed_results, hub_version, firmware_version, database)


    def process_h3bulk_data(self, post_data_bytes: bytes, firmware_version: str, database: Database):
        """Parses and logs sensor data from a binary H3 bulk payload."""
        parsed_results = parse_h3bulk_payload(post_data_bytes, firmware_version)
        self.process_parsed_results(parsed_results, "h3", firmware_version, database)


    def process_parsed_results(self, parsed_results: list[dict], hub_version: str, firmware_version: str, database: Database):
        if hub_version.upper() not in self.server.detected_versions:
            logging.info(f"Detected Efergy Hub version: {hub_version.upper()} - {firmware_version}")
            self.server.detected_versions.add(hub_version.upper())

        for data in parsed_results:
            try:
                if data["type"] == "EFMS":
                    sid = data["sid"]
                    for key, num in data["metrics"]:
                        logging.debug(f"[EFMS1] SID={sid}, Metric={key}, Value={num}")
                    
                    if data["rssi"] is not None:
                        logging.debug(f"[EFMS1] SID={sid}, RSSI={data['rssi']}")
                else:
                    sid = data["sid"]
                    label = data["label"]
                    value = data["value"]
                    firmware_version = data.get("firmware_version", firmware_version)
                    timestamp = data.get("timestamp")

                    if not is_valid_power_reading(value):
                        logging.warning(f"Skipping invalid power reading for {label}: {value}")
                        continue

                    logging.debug(f"Logging sensor: {label}, raw: {value}")
                    database.log_data(label, value, firmware_version, timestamp=timestamp)

                    # Publish power reading
                    self.server.mqtt_manager.publish_power(label, sid, hub_version, firmware_version, value)

            except Exception as e:
                logging.error(f"Unexpected error processing parsed data {data}: {e}")


    def log_message(self, format, *args):
        """
        Suppress default logging
        """
        return


def run_server(database: Database, host: str = '0.0.0.0', port: int = 5000):
    """
    Starts the HTTP server.

    Args:
        database: The initialized Database instance.
        host: The host address to bind to.
        port: The port to listen on.
    """
    server_address = (host, port)

    httpd = EfergyHTTPServer(
        server_address,
        FakeEfergyServer,
        database=database,
        mqtt_manager=mqtt_manager,
    )

    logging.info(f"Serving HTTP on {host} port {port}...")

    try:
        aggregator = Aggregator(db_instance, mqtt_manager)
        aggregator.start()
    except Exception:
        logging.exception("Failed to start aggregator thread")

    # Publish startup discovery for all known sensors
    mqtt_manager.publish_startup_discovery(database.get_all_labels())

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Server shutting down...")
        httpd.server_close()


if __name__ == '__main__':
    # Configure logging
    logging_level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=logging_level,
        format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
    )

    # Startup banner
    logging.info("=" * 60)
    logging.info("  Efergy Hub Server")
    logging.info(f"  Version: {__version__}")
    logging.info("=" * 60)
    logging.info(f"  Python: {sys.version.split()[0]}")
    logging.info(f"  Port: {SERVER_PORT}")
    logging.info(f"  Logging level: {LOG_LEVEL}")
    logging.info(f"  MQTT: {'enabled' if MQTT_ENABLED else 'disabled'}")
    logging.info(f"  HA discovery: {'enabled' if HA_DISCOVERY else 'disabled'}")
    logging.info(f"  Monthly reset: {ENERGY_MONTHLY_RESET}")
    logging.info(f"  Retention months: {HISTORY_RETENTION_MONTHS}")
    logging.info("=" * 60)

    logging.debug(f"  SQL timeout: {SQLITE_TIMEOUT}")
    logging.debug(f"  SQL retry (R|D): {SQLITE_RETRIES} | {SQLITE_RETRY_DELAY}")
    logging.debug(f"  Power value template H1: {POWER_VALUE_TEMPLATE_H1}")
    logging.debug(f"  Power unit of measurement H1: {POWER_UNIT_OF_MEASUREMENT_H1}")
    logging.debug(f"  Power value template H2: {POWER_VALUE_TEMPLATE_H2}")
    logging.debug(f"  Power unit of measurement H2: {POWER_UNIT_OF_MEASUREMENT_H2}")
    logging.debug(f"  Power value template H3: {POWER_VALUE_TEMPLATE_H3}")
    logging.debug(f"  Power unit of measurement H3: {POWER_UNIT_OF_MEASUREMENT_H3}")
    logging.debug(f"  Energy value template: {ENERGY_VALUE_TEMPLATE}")
    logging.debug(f"  Energy unit of measurement: {ENERGY_UNIT_OF_MEASUREMENT}")
    logging.debug("=" * 60)

    # Adjust this path as needed for your project structure
    DB_FILE_PATH = Path(__file__).resolve().parent / "data/readings.db"

    # Initialize the database
    db_instance = Database(DB_FILE_PATH)

    # Create tables and indices
    db_instance.setup()

    # Initialize MQTT
    mqtt_manager = MQTTManager()

    # Start the server, passing the database instance
    run_server(db_instance, port=SERVER_PORT)
