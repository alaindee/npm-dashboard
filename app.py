import json
import logging
import os
import time

from flask import Flask, jsonify, render_template

import config
import demo_data
import health
from npm_client import NPMClient, NPMAuthError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
START_TIME = time.time()

client = NPMClient(config.NPM_BASE_URL, config.NPM_EMAIL, config.NPM_PASSWORD, config.REQUEST_TIMEOUT_SECONDS)

_cache = {"hosts": None, "redirections": None, "streams": None, "version": None, "fetched_at": 0}
_cache_lock_msg = None


def load_descriptions():
    if os.path.exists(config.DESCRIPTIONS_FILE):
        try:
            with open(config.DESCRIPTIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            log.exception("Could not read descriptions file")
    return {}


def route_key(domain, port):
    return f"{domain}:{port}"


def fetch_from_npm(force=False):
    """Refreshes the in-process cache of NPM data. Falls back to demo data
    when DEMO_MODE is on or when NPM can't be reached, so the dashboard
    always has something to show."""
    global _cache_lock_msg
    now = time.time()
    if not force and _cache["hosts"] is not None and (now - _cache["fetched_at"]) < config.NPM_POLL_INTERVAL_SECONDS:
        return

    if config.DEMO_MODE:
        _cache.update(
            hosts=demo_data.DEMO_PROXY_HOSTS,
            redirections=demo_data.DEMO_REDIRECTION_HOSTS,
            streams=demo_data.DEMO_STREAMS,
            version=demo_data.DEMO_VERSION,
            fetched_at=now,
        )
        _cache_lock_msg = None
        return

    try:
        hosts = client.get_proxy_hosts()
        redirections = client.get_redirection_hosts()
        streams = client.get_streams()
        version = client.get_version()
        _cache.update(hosts=hosts, redirections=redirections, streams=streams, version=version, fetched_at=now)
        _cache_lock_msg = None
    except NPMAuthError as e:
        _cache_lock_msg = f"{e} — showing demo data until this is fixed."
        log.error("NPM auth not configured: %s", e)
        _fallback_to_demo(now)
    except Exception as e:
        _cache_lock_msg = f"Could not reach NPM at {config.NPM_BASE_URL}: {e} — showing demo data until this is fixed."
        log.exception("Failed to fetch from NPM")
        _fallback_to_demo(now)


def _fallback_to_demo(now):
    # Keep the dashboard useful even when NPM is unreachable/misconfigured,
    # rather than rendering an empty page.
    if _cache["hosts"] is None:
        _cache.update(
            hosts=demo_data.DEMO_PROXY_HOSTS,
            redirections=demo_data.DEMO_REDIRECTION_HOSTS,
            streams=demo_data.DEMO_STREAMS,
            version=demo_data.DEMO_VERSION,
            fetched_at=now,
        )


def build_routes():
    """Normalizes proxy hosts + redirection hosts + streams into one flat
    list of route dicts the frontend can render, each tagged with a health
    key so the background checker can test the real backend socket."""
    fetch_from_npm()
    descriptions = load_descriptions()
    routes = []

    for h in _cache["hosts"] or []:
        for domain in h.get("domain_names", []):
            key = route_key(domain, h.get("forward_port"))
            routes.append(
                {
                    "key": key,
                    "domain": domain,
                    "type": "Published application",
                    "scheme": h.get("forward_scheme", "http"),
                    "host": h.get("forward_host"),
                    "port": h.get("forward_port"),
                    "ssl": bool(h.get("ssl_forced")) or bool(h.get("certificate_id")),
                    "enabled": bool(h.get("enabled", True)),
                    "description": descriptions.get(domain, ""),
                }
            )

    for h in _cache["redirections"] or []:
        for domain in h.get("domain_names", []):
            key = route_key(domain, 0)
            routes.append(
                {
                    "key": key,
                    "domain": domain,
                    "type": "Redirect",
                    "scheme": h.get("forward_scheme", "http"),
                    "host": h.get("forward_domain_name", ""),
                    "port": None,
                    "ssl": bool(h.get("ssl_forced")) or bool(h.get("certificate_id")),
                    "enabled": bool(h.get("enabled", True)),
                    "description": descriptions.get(domain, ""),
                }
            )

    for s in _cache["streams"] or []:
        label = f"tcp/{s.get('incoming_port')}"
        key = route_key(label, s.get("forwarding_port"))
        routes.append(
            {
                "key": key,
                "domain": label,
                "type": "Stream",
                "scheme": "tcp" if s.get("tcp_forwarding") else "udp",
                "host": s.get("forwarding_host"),
                "port": s.get("forwarding_port"),
                "ssl": False,
                "enabled": bool(s.get("enabled", True)),
                "description": descriptions.get(label, ""),
            }
        )

    return routes


def routes_for_health_check():
    out = []
    for r in build_routes():
        if r["enabled"] and r.get("host") and r.get("port"):
            out.append({"key": r["key"], "host": r["host"], "port": r["port"]})
    return out


checker = health.HealthChecker(routes_for_health_check)
checker.start()


@app.route("/")
def index():
    return render_template("index.html", dashboard_name=config.DASHBOARD_NAME)


@app.route("/api/routes")
def api_routes():
    routes = build_routes()
    out = []
    for r in routes:
        hs = health.get_status(r["key"])
        out.append(
            {
                **r,
                "service_url": f"{r['scheme']}://{r['host']}:{r['port']}" if r.get("port") else (r.get("host") or ""),
                "health": {
                    "status": hs["status"],
                    "uptime_human": health.humanize_duration(hs["uptime_seconds"]) if hs["status"] != "unknown" else "-",
                    "uptime_pct": hs["uptime_pct"],
                    "response_ms": hs["response_ms"],
                },
            }
        )
    return jsonify(out)


@app.route("/api/summary")
def api_summary():
    routes = build_routes()
    enabled = [r for r in routes if r["enabled"]]
    healthy = sum(1 for r in enabled if health.get_status(r["key"])["status"] == "up")
    unknown = sum(1 for r in enabled if health.get_status(r["key"])["status"] == "unknown")
    if not enabled:
        overall = "No routes"
    elif healthy == len(enabled):
        overall = "Healthy"
    elif healthy + unknown == len(enabled):
        overall = "Checking..."
    elif healthy == 0:
        overall = "Down"
    else:
        overall = "Degraded"

    return jsonify(
        {
            "dashboard_name": config.DASHBOARD_NAME,
            "npm_base_url": config.NPM_BASE_URL,
            "npm_version": _cache.get("version"),
            "demo_mode": config.DEMO_MODE,
            "error": _cache_lock_msg,
            "active_routes": len(enabled),
            "total_routes": len(routes),
            "status": overall,
            "dashboard_uptime": health.humanize_duration(time.time() - START_TIME),
            "health_check_interval_seconds": config.HEALTH_CHECK_INTERVAL_SECONDS,
        }
    )


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=False)
