import logging

import pytest
import sqlite3
import time
from database import Database

@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_readings.db"

@pytest.fixture
def db(db_path):
    database = Database(db_path)
    database.setup()
    return database

def test_database_setup(db_path):
    db = Database(db_path)
    db.setup()
    assert db_path.exists()
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        assert "labels" in tables
        assert "readings" in tables
        assert "energy_hourly" in tables


def test_log_data_and_labels(db):
    db.log_data("test_label", 100.0, "2.3.7", timestamp=1000)
    db.log_data("test_label", 200.0, "2.3.7", timestamp=1100)
    db.log_data("another_label", 50.0, "2.3.7", timestamp=1200)
    
    labels_data = db.get_all_labels()
    labels = [item["label"] for item in labels_data]
    assert "test_label" in labels
    assert "another_label" in labels
    assert len(labels) == 2
    
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM readings ORDER BY timestamp")
        readings = [row[0] for row in cursor.fetchall()]
        assert readings == [100.0, 200.0, 50.0]


def test_aggregate_one_hour(db):
    # Hour starts at 3600
    hour_start = 3600
    
    # Add some readings in this hour
    # efergy_h1 uses (PF * V * I/1000) / 1000 for kW
    db.log_data("efergy_h1_test", 1000.0, "2.3.7", timestamp=hour_start)      # 1000mA -> (0.6 * 230 * 1) / 1000 = 0.138 kW
    db.log_data("efergy_h1_test", 2000.0, "2.3.7", timestamp=hour_start + 1800) # 2000mA -> 0.276 kW
    db.log_data("efergy_h1_test", 1000.0, "2.3.7", timestamp=hour_start + 3600) # Next hour, shouldn't be included in this aggregation
    
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        kwh = db.aggregate_one_hour(cursor, hour_start)
        
    # Calculation:
    # 0.138 kW for 1800s = 0.138 * (1800/3600) = 0.069 kWh
    # 0.276 kW for 1800s = 0.276 * (1800/3600) = 0.138 kWh
    # Total = 0.069 + 0.138 = 0.207 kWh
    # Note: the code uses (rows[i+1][0] - rows[i][0]) for interval.
    # So for row 0 (ts=3600), interval = 5400 - 3600 = 1800.
    # For row 1 (ts=5400), it's the last row, so it uses the same interval as previous: 1800.
    
    expected_kwh = (0.138 * 0.5) + (0.276 * 0.5)
    assert kwh == pytest.approx(expected_kwh)


def test_aggregate_hours(db):
    now = int(time.time())
    # Round to start of 2 hours ago to ensure we have a full hour to process
    hour1_start = (now - 7200) - (now % 3600)
    hour2_start = hour1_start + 3600
    
    db.log_data("efergy_h3_test", 100.0, "2.3.7", timestamp=hour1_start) # h3 uses value/10/1000 = 0.01 kW
    db.log_data("efergy_h3_test", 100.0, "2.3.7", timestamp=hour1_start + 3599)
    
    processed = db.aggregate_hours()
    assert processed >= 1
    
    total_energy = db.get_total_energy()
    assert total_energy > 0


def test_truncate_old_data(db):
    # Log some "old" data
    now = int(time.time())
    two_months_ago = now - (62 * 24 * 3600)
    
    db.log_data("old_label", 100.0, "2.3.7", timestamp=two_months_ago)
    db.log_data("new_label", 100.0, "2.3.7", timestamp=now)
    
    # Aggregate to have something in energy_hourly to
    # Need to make sure we have a full hour for the old data
    old_hour_start = two_months_ago - (two_months_ago % 3600)
    db.log_data("old_label", 100.0, "2.3.7", timestamp=old_hour_start)
    db.log_data("old_label", 100.0, "2.3.7", timestamp=old_hour_start + 3599)
    
    with sqlite3.connect(db.db_path) as conn:
        db.aggregate_one_hour(conn.cursor(), old_hour_start)
        conn.commit()
        
    # Truncate to 1 month
    deleted = db.truncate_old_data(1)
    assert deleted > 0
    
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM readings WHERE timestamp < ?", (now - 31*24*3600,))
        assert cursor.fetchone()[0] == 0
        
        cursor.execute("SELECT count(*) FROM energy_hourly WHERE hour_start < ?", (now - 31*24*3600,))
        assert cursor.fetchone()[0] == 0


def test_reconnect(db):
    db.log_data("reconnect_test", 123.0, "2.3.7", timestamp=1000)

    # Simulate connection loss
    if db._conn:
        db._conn.close()
        db._conn = None

    # Now log again — _get_connection should reconnect automatically
    db.log_data("reconnect_test", 456.0, "2.3.7", timestamp=1100)

    # Verify both entries exist
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM readings WHERE label_id = (SELECT label_id FROM labels WHERE label=?) ORDER BY timestamp", ("reconnect_test",))
        rows = [row[0] for row in cursor.fetchall()]

    assert rows == [123.0, 456.0]


def test_connection_error_recovery(db, caplog):
    """
    Simulate a sqlite3.OperationalError on the first connection attempt.
    Verify that the error is logged and the connection recovers.
    """
    caplog.set_level(logging.WARNING)

    # Save original _connect method
    original_connect = db._connect
    call_count = {"count": 0}

    def failing_connect():
        if call_count["count"] == 0:
            call_count["count"] += 1
            # Simulate OperationalError on first call
            raise sqlite3.OperationalError("simulated DB failure")
        else:
            original_connect()

    # Patch the _connect method
    db._connect = failing_connect

    # Attempt to log data — first attempt will fail, second should succeed
    db.log_data("error_test_label", 42.0, "2.3.7")

    # Check that a warning was logged
    warnings = [rec for rec in caplog.records if "DB connection error" in rec.message]
    assert len(warnings) > 0

    # Check that the data was successfully logged despite the first failure
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM readings WHERE label_id = (SELECT label_id FROM labels WHERE label=?)", ("error_test_label",))
        row = cursor.fetchone()
        assert row[0] == 42.0

    # Restore original method
    db._connect = original_connect
