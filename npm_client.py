"""
Thin client for the Nginx Proxy Manager REST API.

NPM's admin UI (the Vue app you log into on port 81) talks to a REST API
under /api that isn't officially "public" but is stable and simple:

    POST /api/tokens                 { identity, secret }  -> { token, expires }
    GET  /api/nginx/proxy-hosts       -> [ { domain_names, forward_host, ... } ]
    GET  /api/nginx/redirection-hosts -> [ ... ]
    GET  /api/nginx/streams           -> [ ... ]
    GET  /api                         -> { version, ... }

Tokens are short-lived (about a day); this client re-authenticates on 401s
and caches the token in memory in the meantime.
"""
import time
import logging

import requests

import config

log = logging.getLogger("npm_client")


class NPMAuthError(Exception):
    pass


class NPMClient:
    def __init__(self, base_url, email, password, timeout=4.0):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.timeout = timeout
        self._token = None
        self._token_expires_at = 0
        self._npm_version = None

    def _authenticate(self):
        if not self.email or not self.password:
            raise NPMAuthError("NPM_EMAIL / NPM_PASSWORD are not configured")
        resp = requests.post(
            f"{self.base_url}/api/tokens",
            json={"identity": self.email, "secret": self.password},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["token"]
        # NPM returns an ISO expiry; fall back to a conservative 12h if absent.
        self._token_expires_at = time.time() + 12 * 3600
        log.info("Authenticated to NPM at %s", self.base_url)

    def _headers(self):
        if not self._token or time.time() > self._token_expires_at - 60:
            self._authenticate()
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path):
        url = f"{self.base_url}{path}"
        resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        if resp.status_code == 401:
            # token expired/invalid server-side -- re-auth once and retry
            self._authenticate()
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_version(self):
        try:
            data = requests.get(f"{self.base_url}/api", timeout=self.timeout).json()
            self._npm_version = data.get("version") or data.get("result", {}).get("version")
        except Exception:
            log.exception("Could not fetch NPM version")
        return self._npm_version

    def get_proxy_hosts(self):
        return self._get("/api/nginx/proxy-hosts?expand=owner,access_list,certificate")

    def get_redirection_hosts(self):
        return self._get("/api/nginx/redirection-hosts?expand=owner,certificate")

    def get_streams(self):
        return self._get("/api/nginx/streams?expand=owner,certificate")
