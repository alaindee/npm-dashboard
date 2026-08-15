# npm-dashboard

A small self-hosted dashboard for **Nginx Proxy Manager (NPM)**, styled after
Cloudflare's Tunnel overview page: a hub-and-spoke diagram of your routes,
plus a routes table with live per-backend health and uptime — something NPM
doesn't show you natively.

It pulls its data from NPM's own REST API (the same one NPM's admin UI
uses), so there's nothing to configure inside NPM itself beyond a login it
can use.

## What it shows

- **Metrics row**: active vs. total routes, overall status, dashboard uptime.
- **Route diagram**: every proxy host / redirection / stream, connected into
  a central hub, mirroring the Cloudflare tunnel view.
- **Route table**: destination domain, type, backend service (`host:port`),
  whether SSL is enforced, live up/down status, uptime, and an optional
  description you supply yourself.
- **Health checks NPM doesn't do**: this dashboard opens a TCP connection to
  each backend `host:port` on an interval (default 30s) and tracks uptime %
  over time — filling the gap where Cloudflare's tunnel page shows
  "Healthy" / uptime for the tunnel daemon itself.

Until you configure real credentials, it runs in **demo mode** with sample
data so you can see what it looks like immediately.

## 1. Create an NPM login for the dashboard

The dashboard needs an NPM user it can authenticate as. Your existing admin
login works fine; if you'd rather not reuse it, create a second user in
NPM's admin UI (**Users → Add User**) just for this.

## 2. Configure

```bash
cp .env.example .env
touch state.json descriptions.json
echo '{}' > descriptions.json
```

Edit `.env`:

```
NPM_BASE_URL=http://192.168.1.10:81
NPM_EMAIL=dashboard@yourdomain.com
NPM_PASSWORD=your-password
```

Optionally copy `descriptions.example.json` into `descriptions.json` and
fill in whatever notes you want to show per domain — NPM has no
"description" field on a proxy host, so this is a local override file the
dashboard merges in.

## 3. Run it

### With Docker (recommended)

```bash
docker compose up -d --build
```

Then open `http://<this-host>:5080`.

If NPM and your backend services (the `192.168.x.x:port` targets) are all
on the same LAN as the Docker host but the container's bridge network can't
reach them, uncomment `network_mode: host` in `docker-compose.yml` and drop
the `ports:` block (host networking uses the port straight off `PORT` in
`.env`).

### Without Docker

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Notes & limitations

- NPM's REST API isn't officially "public" but has been stable for years.
  If a future NPM version changes endpoint shapes, check
  `http://<npm-host>:81/api/schema` (NPM serves its own OpenAPI schema) and
  adjust `npm_client.py` accordingly.
- NPM tokens expire after roughly a day; `npm_client.py` re-authenticates
  automatically on 401s.
- Health checks are a plain TCP connect to the backend, not an HTTP status
  check — good enough to know if a service is listening, but it won't catch
  an app that's up but returning 500s. Swap `_check_tcp` in `health.py` for
  an HTTP `HEAD` request if you want that.
- Uptime % is measured from when this dashboard started tracking a route,
  not from NPM/backend install time — it only knows what it's observed.
- Redirection hosts and streams are included but won't have a
  `forward_host`/`forward_port` in the same shape as proxy hosts in every
  NPM version; if your instance errors on those endpoints, comment out the
  corresponding block in `app.py`'s `build_routes()`.

## Project layout

```
app.py               Flask app + REST endpoints (/api/summary, /api/routes)
npm_client.py         Talks to NPM's REST API (auth, proxy hosts, etc.)
health.py             Background TCP health checker + uptime tracking
demo_data.py           Sample data shown before you configure real credentials
config.py              Env var loading
templates/index.html  The dashboard UI (single page, vanilla JS)
descriptions.json      Your own domain -> description overrides (optional)
```
