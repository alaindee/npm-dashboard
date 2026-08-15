"""Configuration loaded from environment variables (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# Nginx Proxy Manager connection
NPM_BASE_URL = os.getenv("NPM_BASE_URL", "http://localhost:81").rstrip("/")
NPM_EMAIL = os.getenv("NPM_EMAIL", "")
NPM_PASSWORD = os.getenv("NPM_PASSWORD", "")

# Behavior
DEMO_MODE = _bool("DEMO_MODE", default=(not NPM_EMAIL or not NPM_PASSWORD))
HEALTH_CHECK_INTERVAL_SECONDS = int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "30"))
NPM_POLL_INTERVAL_SECONDS = int(os.getenv("NPM_POLL_INTERVAL_SECONDS", "60"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "4"))

# Optional local override file: maps a domain -> human description, since NPM
# itself has no "description" field on a proxy host.
DESCRIPTIONS_FILE = os.getenv("DESCRIPTIONS_FILE", os.path.join(os.path.dirname(__file__), "descriptions.json"))

# Where health/uptime state is persisted between restarts.
STATE_FILE = os.getenv("STATE_FILE", os.path.join(os.path.dirname(__file__), "state.json"))

PORT = int(os.getenv("PORT", "5080"))
HOST = os.getenv("HOST", "0.0.0.0")

DASHBOARD_NAME = os.getenv("DASHBOARD_NAME", "home-proxy")
