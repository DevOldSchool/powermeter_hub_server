import pytest
import http.client
import threading
import socket
from unittest.mock import MagicMock
from hub_server import EfergyHTTPServer, FakeEfergyServer

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def mock_mqtt():
    return MagicMock()

@pytest.fixture
def test_server(mock_db, mock_mqtt):
    """
    Starts the HTTP server in a background thread and ensures clean shutdown.
    """
    server_address = ('127.0.0.1', 0)  # 0 = pick a free port
    httpd = EfergyHTTPServer(server_address, FakeEfergyServer, mock_db, mock_mqtt)
    port = httpd.server_port

    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()

    # Wait until the server socket is ready
    timeout = 1.0
    while timeout > 0:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                break
        except ConnectionRefusedError:
            timeout -= 0.1
    else:
        raise RuntimeError("Server failed to start")

    yield ('127.0.0.1', port)

    # Clean shutdown
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def http_request(host, port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        conn.close()


def test_get_key(test_server):
    host, port = test_server
    status, data = http_request(host, port, "GET", "/get_key.html")
    assert status == 200
    assert data == b"TT|a1bCDEFGHa1zZ\n"


def test_check_key(test_server):
    host, port = test_server
    status, data = http_request(host, port, "GET", "/check_key.html")
    assert status == 200
    assert data == b"success"


def test_404(test_server):
    host, port = test_server
    status, data = http_request(host, port, "GET", "/unknown")
    assert status == 404


def test_post_h2(test_server, mock_db, mock_mqtt):
    host, port = test_server
    payload = b"741459|1|EFCT|P1,2479.98"
    headers = {"Content-Type": "text/plain", "Content-Length": str(len(payload))}

    status, data = http_request(host, port, "POST", "/h2", body=payload, headers=headers)
    assert status == 200
    assert data == b"success"

    assert mock_db.log_data.called
    assert mock_mqtt.publish_power.called


def test_post_h3_rejects_invalid_power_readings(test_server, mock_db, mock_mqtt):
    host, port = test_server
    payload = b"\r\n".join([
        b"782792|1|EFCT|P1,12761.72|-61",
        b"782792|1|EFCT|P1,2147483647.2147483647|-61",
        b"782792|1|EFCT|P1,2147483647|-61",
        b"782792|1|EFCT|P1,nan|-61",
        b"782792|1|EFCT|P1,inf|-61",
        b"782792|1|EFCT|P1,12285.65|-61",
    ])
    headers = {
        "Content-Type": "application/eh-data",
        "Content-Length": str(len(payload)),
        "X-Version": "3.7.1",
    }

    status, data = http_request(host, port, "POST", "/h3", body=payload, headers=headers)

    assert status == 200
    assert data == b"success"
    assert mock_db.log_data.call_count == 2
    assert [call.args[1] for call in mock_db.log_data.call_args_list] == [12761.72, 12285.65]
    assert mock_mqtt.publish_power.call_count == 2
    assert [call.args[4] for call in mock_mqtt.publish_power.call_args_list] == [12761.72, 12285.65]


def test_post_h3bulk(test_server, mock_db, mock_mqtt):
    host, port = test_server
    payload = bytes.fromhex(
        """
        C7 B3 76 69 2C 16 0D 59 12 0D 7A 16 0D 27 12 0D
        00 00 00 24 00 00 DD F3 36 44 6E 26 00 00 A6 81
        02 45 94 20 00 3B B3 6D 01 45 C1 22 00 3B AC 2E
        36 45 B2 24 00 3B AC EA 34 44 6D 26 00 3B B0 95
        FD 44 E7 20 00 77 6B 1C 02 45 65 22 00 77 60 FF
        """.replace("\n", " ").strip()
    )
    headers = {
        "Content-Type": "application/eh-datalog",
        "Content-Length": str(len(payload)),
        "X-Version": "3.7.1",
    }

    status, data = http_request(host, port, "POST", "/h3bulk", body=payload, headers=headers)
    assert status == 200
    assert data == b"success"

    assert mock_db.log_data.call_count == 7
    first_call = mock_db.log_data.call_args_list[0]
    assert first_call.args[0] == "efergy_h3_857644"
    assert first_call.args[1] == pytest.approx(7286.0)
    assert first_call.args[2] == "3.7.1"
    assert first_call.kwargs["timestamp"] == 1769386951

    assert mock_mqtt.publish_power.call_count == 7


def test_post_recjson_h1(test_server, mock_db, mock_mqtt):
    host, port = test_server
    payload = b'json=AABBCCDDDDDD|694851F9|v1.0.1|{"data":[[610965,"mA","E1",33314,0,0,65535]]}|39ef0bdc14b52df375b79555f059b52f'
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(payload))}

    status, data = http_request(host, port, "POST", "/recjson", body=payload, headers=headers)
    assert status == 200
    assert data == b"success"

    assert mock_db.log_data.called
    assert mock_mqtt.publish_power.called


def test_post_ping(test_server):
    host, port = test_server
    payload = b"123456|789012"
    headers = {"Content-Type": "application/eh-ping", "Content-Length": str(len(payload))}

    status, data = http_request(host, port, "POST", "/any", body=payload, headers=headers)
    assert status == 200
    assert data == b"success"
