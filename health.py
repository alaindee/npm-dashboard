"""
Background health checking + uptime tracking for each route.

NPM itself doesn't monitor whether the backend behind a proxy host is
actually up -- it just holds the nginx config. This module fills that gap:
for every route we know about, periodically try to open the backend
(host, port) and time it. State (current status, when it last changed,
and a rolling record of downtime) is kept in memory and persisted to a
small JSON file so uptime survives a restart of the dashboard itself.
"""
import json
import logging
import os
import socket
import threading
import time

import config

log = logging.getLogger("health")

_lock = threading.Lock()
_state = {}  # key -> {status, since, last_checked, last_response_ms, checks_total, checks_up}


def _load_state():
    global _state
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                _state = json.load(f)
        except Exception:
            log.exception("Could not load state file, starting fresh")
            _state = {}


def _save_state():
    try:
        with open(config.STATE_FILE, "w") as f:
            json.dump(_state, f)
    except Exception:
        log.exception("Could not persist state file")


def _check_tcp(host, port, timeout):
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True, (time.time() - start) * 1000
    except Exception:
        return False, None


def check_route(key, host, port, timeout=None):
    timeout = timeout or config.REQUEST_TIMEOUT_SECONDS
    up, response_ms = _check_tcp(host, port, timeout)
    now = time.time()

    with _lock:
        entry = _state.get(key) or {
            "status": "unknown",
            "since": now,
            "checks_total": 0,
            "checks_up": 0,
        }
        was_up = entry["status"] == "up"
        entry["checks_total"] = entry.get("checks_total", 0) + 1
        if up:
            entry["checks_up"] = entry.get("checks_up", 0) + 1
        if up and not was_up:
            entry["since"] = now
        elif not up and was_up:
            entry["since"] = now
        entry["status"] = "up" if up else "down"
        entry["last_checked"] = now
        entry["last_response_ms"] = round(response_ms, 1) if response_ms else None
        _state[key] = entry
    return entry


def get_status(key):
    with _lock:
        entry = _state.get(key)
    if not entry:
        return {
            "status": "unknown",
            "uptime_seconds": 0,
            "uptime_pct": None,
            "last_checked": None,
            "response_ms": None,
        }
    total = entry.get("checks_total", 0) or 1
    up = entry.get("checks_up", 0)
    return {
        "status": entry["status"],
        "uptime_seconds": max(0, time.time() - entry.get("since", time.time())),
        "uptime_pct": round(100 * up / total, 1),
        "last_checked": entry.get("last_checked"),
        "response_ms": entry.get("last_response_ms"),
    }


def humanize_duration(seconds):
    if seconds is None:
        return "-"
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return "<1m"


class HealthChecker(threading.Thread):
    """Runs in the background, re-checking whatever route list the app
    hands it every HEALTH_CHECK_INTERVAL_SECONDS."""

    def __init__(self, get_routes_fn, interval=None):
        super().__init__(daemon=True)
        self.get_routes_fn = get_routes_fn
        self.interval = interval or config.HEALTH_CHECK_INTERVAL_SECONDS
        self._stop = threading.Event()
        _load_state()

    def run(self):
        while not self._stop.is_set():
            try:
                routes = self.get_routes_fn()
                for r in routes:
                    check_route(r["key"], r["host"], r["port"])
                _save_state()
            except Exception:
                log.exception("Health check pass failed")
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
