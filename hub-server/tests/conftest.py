import os

# Set environment variables for tests before any other modules are imported
os.environ["TELEMETRY_ENABLED"] = "false"
os.environ["TELEMETRY_URL"] = ""