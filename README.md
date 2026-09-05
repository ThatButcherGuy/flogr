# fLOGr

A self-hosted web app for logging your fuel purchases and tracking vehicle fuel economy. Enter each refuel, and fLOGr calculates litres/100km, cost per 100 km, price trends, and per-vehicle comparisons over time.

Built with **Flask** + **SQLite** + **Chart.js**, styled with **Bootstrap 5**. Developed by ThatButcherGuy.

---

## Features at a glance

- **Quick log entry** — enter a refuel on the go (vehicle, fuel, litres, price/L, kilometres, location, optional comments).
- **Edit / delete records** — fix typos or remove a mistaken entry; the vehicle odometer is adjusted automatically.
- **Smart purchase locations** — store each retailer + suburb once and reuse it; rename a location and it updates every past log.
- **Stats & Reports** — summary cards, global statistics, per-vehicle comparison, and interactive charts (economy, price/L, litres, spend by location, monthly spend, fuel price history).
- **Vehicle garage** — manage your vehicles and view detailed per-vehicle stats.
- **Full-tank accuracy** — a "Partial tank" flag lets you log top-ups that are excluded from fuel-economy calculations but still counted in litres/spend.
- **Two-factor authentication (TOTP)** and optional **Authentik (OIDC) SSO**.
- **Scoped API** — generate tokens to let programs (e.g. an AI agent) read your data.
- **Logging & audit trail** — request logs to `docker logs`, plus a per-user **Activity Log** of every data/account change.
- **CSV export** — export your log, optionally filtered.

---

## Quick start (Docker)

### docker-compose.yml

```yaml
services:
  flogr:
    image: docker.io/thatbutcherguy/flogr-docker:latest
    container_name: flogr
    ports:
      - "15001:8080"              # host : container
    volumes:
      - /path/to/flogr/data:/flask-app/data   # persist the SQLite database
    environment:
      - TZ=Australia/Canberra
      - DATABASE_PATH=/flask-app/data/flogr.db
      - PUID=568
      - PGID=568
      - LOG_LEVEL=INFO            # DEBUG / INFO / WARNING / ERROR
      # - LOG_FORMAT=json         # uncomment for structured (JSON) logs
      # Optional: Authentik OIDC SSO
      # - AUTHENTIK_CLIENT_ID=********
      # - AUTHENTIK_CLIENT_SECRET=********
      # - AUTHENTIK_ISSUER_URL=https://auth.example.com/application/o/flogr/
    restart: unless-stopped
    networks:
      - flogr

networks:
  flogr:
    external: true
```

The app listens on **port 8080** in the container, mapped to `15001` on the host (behind a reverse proxy if desired).

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `data/flogr.db` | Where the SQLite database is stored. |
| `SECRET_KEY` | | Flask session key. Set a long random value in production. |
| `LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FORMAT` | `plain` | `json` emits one JSON object per line for log viewers; `plain` is human-readable. |
| `AUTHENTIK_CLIENT_ID` / `_SECRET` / `ISSUER_URL` | (unset) | When all three are set, Authentik OIDC login is enabled. |
| `GUNICORN_*` | | Optional Gunicorn tuning (processes, threads, timeout, bind). |

---

## Using fLOGr

### Authentication

Two login methods, switched per-user from **Settings**:

- **Password login** — default; passwords are hashed with Werkzeug.
- **Authentik (OIDC)** — optional SSO. `Settings → Authentik (OIDC) Login` toggles it per user. If Authentik is unreachable, the login page warns you and you can fall back to your password.

**Two-factor authentication (TOTP)** — enable from Settings, scan the secret into an authenticator app, then enter a code to confirm. Save your **10 recovery codes** (each usable once). 2FA applies to password login; Authentik handles its own MFA.

### Enter a Record (home page)

Once logged in, the home page is a fast refuel entry form.

> **For accurate fuel-economy maths:** fill the tank to the **same level** each time — the fullest point is most repeatable — and log **every** refuel. If you forget one, a close guess is better than nothing. Mark a **partial top-up** as "Partial tank" so it's excluded from L/100km (but still counted in spend/litres).

Fields:
- **Vehicle** — required selection from your Garage.
- **Fuel type** — defaults to the vehicle's fuel; changeable (handy for dual-fuel).
- **Date** — defaults to today, cannot be in the future.
- **Receipt number** — optional.
- **Purchased at** — choose an existing location or add one inline.
- **Litres** — to 2 decimal places.
- **Price per litre** — to 3 decimal places; include any checkout discounts.
- **Kilometres** — how far you drove on the previous tank; added to the vehicle's odometer.
- **Partial tank** — check for a top-up that isn't a full tank.
- **Comments** — optional free text.

For each record fLOGr calculates **sale price** (`litres × price/L`) and **L/100km** (`litres / km × 100`).

### View Log

All your records, newest first. Sortable by any column, searchable, and filterable by vehicle. From here you can **edit** or **delete** entries (odometer adjusts automatically), and **Export CSV** for all records or the selected vehicle.

The page uses **server-side paging** — it loads instantly and fetches one page of records at a time, so it stays responsive even with thousands of entries.

### Locations

Manage your reusable `Retailer Suburb` purchase locations. Renaming a location updates it across all past log entries; you can't delete a location still referenced by logs.

### Garage

Your vehicles (registration, type, make/model, year, odometer). Add, edit or delete vehicles. Click a registration for full vehicle details (useful on small screens where the Garage table is trimmed).

### Stats

A read-only **numbers** overview of your logs, fully driven by the **filter bar** at the top (vehicle, a custom date range, or a **quick period** — All / 7 / 30 / 90 days / 6 / 12 months / YTD / Financial year (AU)). A banner shows exactly what's being viewed (e.g. *"vehicle ABC · date: Year to date"*):

- **Trend vs Previous Period** — when a date filter is active, compares this period against the equivalent prior window (total spend %, economy L/100km change, distance %, avg days/tank) with green/red change badges.
- **Summary cards** — total spend, litres, distance, combined L/100km, cost/100km, avg cost/tank, best/worst economy (label-above-value).
- **Most Recent Fill** — your latest entry, days since, economy, price, cost, location, and **avg days / tank**.
- **Summary table** — totals and averages across the filtered set, plus **Average days per tank**.
- **Vehicle Comparison** — each vehicle's economy, cost/100km, and range per tank.
- **Location Insights** — most spent at, most frequent, cheapest & most expensive avg $/L, best-economy location, and distinct location count in the period.
- **Vehicles** — links to per-vehicle statistics.

All figures use thousands separators, and dollar values include `$`.

### Vehicle Stats

Click a vehicle's registration on the Stats page (or Garage). Shows vehicle details, summary cards (including **days since last fill** and **avg days / tank**), and the last 20 records for that vehicle. Filter the summary to a date range.

### Reports & Charts

The interactive, graphical analysis hub (also via **"Open Reports & Charts"** on the Stats page). Filter by vehicle, location, a custom date range, or a **quick period** (All / 7 / 30 / 90 days / 6 / 12 months / YTD / Financial year (AU)) — charts and summary cards update instantly, client-side:

- Fuel economy (L/100km) and price/L over time (monthly line charts)
- Litres purchased over time (bar)
- Spend by location (doughnut)
- Fuel price history — avg $/L by year (bar)
- Monthly spend, last 12 months (bar)
- Vehicle comparison — economy and cost/100km (bar)

Data is served by `/api/stats`.

> **Stats vs Reports:** Stats is the readable numbers/table view; Reports is the trend/chart view. They cross-link (Stats → "Open Reports & Charts"; Reports → "View Statistics").

### Settings

- **Appearance** — light / dark / auto theme (also the navbar 🌙/☀️🖥️ toggle).
- **Account & Security** — username, email, Authentik toggle, 2FA enable/disable.
- **API Access** — generate/revoke scoped tokens.
- **Activity Log** — your audit trail (see below).

---

## API (token-authenticated)

Generate a scoped token from **Settings → API Access**. Send it as:

```
Authorization: Bearer flogr_...
```

Endpoints:

| Endpoint | Reads | Scope |
|---|---|---|
| `GET /api/logs` | your log entries | `logs` |
| `GET /api/locations` | your locations | `locations` |
| `GET /api/vehicles` | your vehicles | `vehicles` |

Tokens are read-only by default. Each endpoint needs its named scope, or a token may carry `write` (grants access to all). Only a SHA-256 hash of the token is stored — the raw value is shown **once** at creation. Revoke a token anytime from Settings.

---

## Logging & Audit

**Container logging** — the app writes structured logs to stdout, captured by `docker logs flogr` (alongside Gunicorn's access/error streams). Every request is logged with method, path, status, user ID, source IP and duration. `LOG_LEVEL=DEBUG` shows more detail; `LOG_FORMAT=json` emits one JSON object per line for dashboards.

**Activity Log (audit)** — **Settings → Activity Log** keeps an immutable, per-user trail of data and account changes, kept indefinitely for troubleshooting and traceability:

- **Fuel-log entries** capture full before/after field diffs on create and edit, and a full snapshot on delete.
- **Locations, vehicles, API tokens, account settings, and auth events** (login, failed login, logout, registration, 2FA, OIDC) are recorded as concise summaries.
- Each user sees only their **own** entries.

---

## Database schema

A single SQLite database with these tables:

| Table | Purpose |
|---|---|
| `users` | Accounts, password hash, 2FA secret/codes, OIDC flag. |
| `fuel_types` | Lookup of fuel codes (`U91`, `P98`, `DL`, ...). |
| `vehicles` | Each vehicle in a user's Garage (registration, type, make/model, year, odometer). |
| `log` | Every refuel record (`log.location_id` → `locations.id`, `partial_tank` flag). |
| `locations` | Reusable retailer + suburb purchase locations. |
| `api_tokens` | Scoped API tokens (SHA-256 hashes only). |
| `audit_log` | Per-user activity/audit trail. |

---

## Development

- Repo: self-hosted Gitea at `git.brendoscloud.com` → `brendos-cloud/flogr`.
- Single persistent clone; releases are git tags (`vX.Y.Z`). Semver: **minor** for features, **patch** for fixes/security.
- Database schema lives in `static/schema.sql` (fresh installs); existing installs get new tables/columns via migrations run at app startup. A schema change needs **both**.
- Run locally: `uv venv && source .venv/bin/activate && uv pip install -r requirements.txt`, then set `DATABASE_PATH`, `SECRET_KEY` and start with `python app.py`.

---

## Wish list

- **User account management** — edit/delete users, email + `is_active`, reset / forgot-password.
- **PDF export** of logs and of reports (charts + stats).
- **Unit-of-measure support** — miles, gallons, MPG, other currencies.
- **Vehicle service tracking** and richer **vehicle profiles** (mods with install dates, photo gallery for insurance).

> ✅ **Done recently:** password strength on registration (min 8 chars), auto-rounding of kilometres on entry, container logging, per-user activity/audit log, and avg-days-per-tank + days-since-last-fill stats.