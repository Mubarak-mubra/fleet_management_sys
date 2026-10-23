# Vehicle Management System

Flask + Jinja2 monolith for a small construction fleet: vehicles, trips, fuel
logs, and maintenance records. Server-rendered HTML, SQLite storage
(`DATABASE_URL` overridable), no GPS, no API, no JavaScript framework.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask db upgrade                   # preferred (creates schema from migrations)
# or: flask init-db                # legacy, create_all
flask seed-db                      # optional demo data
flask create-user admin --role admin   # first account (prompts for password)
flask run                          # http://127.0.0.1:5000
```

Every route except `/auth/login` and static assets requires a signed-in
session. Create at least one `admin` before starting the server, otherwise
nobody can get past the login page.

## Deployment

```bash
export FLASK_CONFIG=production
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export DATABASE_URL="sqlite:////var/lib/vms/vms.db"   # optional
# Only if nginx/Caddy sits in front (2 if there is also a CDN/load balancer):
export TRUSTED_PROXY_HOPS=1
gunicorn --workers 3 --bind 0.0.0.0:8000 \
  --access-logfile - --error-logfile - wsgi:app
```

`create_app` refuses to boot in production with the default or a short
`SECRET_KEY`, so a misconfigured deployment fails at startup instead of
running with forgeable sessions. Put TLS in front of it (Caddy/nginx) —
production sets `SESSION_COOKIE_SECURE`, so browsers will only send the
session cookie over HTTPS. Sessions are marked permanent, so the configured
8-hour `PERMANENT_SESSION_LIFETIME` is genuinely enforced: the cookie carries
an `Expires` and `SESSION_COOKIE_REFRESH_EACH_REQUEST` slides it on each
request.

- **Proxies:** by default `TRUSTED_PROXY_HOPS=0`, meaning client-supplied
  `X-Forwarded-*` headers are ignored and `request.remote_addr` is the real
  socket peer. That is deliberate — a forged `X-Forwarded-For` would otherwise
  let an attacker pick a new apparent IP per login attempt and reset the
  brute-force throttle every time. Set it to your hop count **only** when a
  proxy you control terminates the connection and overwrites/appends those
  headers; then `remote_addr`, the throttle key and your access logs all show
  the real client address.
- **Security headers:** every response (pages, error pages, static assets)
  carries a strict `Content-Security-Policy` (`default-src 'none'` with only
  `'self'` allowed), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy: same-origin`,
  `X-Permitted-Cross-Domain-Policies: none` and a restrictive
  `Permissions-Policy`. `Strict-Transport-Security` (1 year, includeSubDomains)
  is added only where `SESSION_COOKIE_SECURE` is on, i.e. HTTPS-only
  production — HSTS cannot be un-sent, so it is never emitted on plain http.
  The CSP holds no `'unsafe-inline'`: the templates contain no inline scripts,
  styles or handler attributes, so introducing one now requires a hash or
  nonce rather than silently weakening the policy. Constants live in
  `app/security.py` (`SECURITY_HEADERS`). gunicorn's own `Server: gunicorn`
  header is added outside the WSGI app and can only be hidden at the proxy
  (`server_tokens off; proxy_hide_header Server;`).
- **Backups:** `flask backup-db` copies the SQLite file using the online
  backup API (safe to run while serving). Schedule it; the database is one
  file and holds the fleet's entire cost history.
- **Accounts:** `flask create-user <name> --role admin|operator|viewer`, or
  the admin-only `/users/` screens. Roles: `admin` (everything incl. account
  management), `operator` (CRUD on fleet records), `viewer` (read-only —
  every POST is refused with 403).

## Routes

| Path | Method | Endpoint |
|---|---|---|
| `/` | GET | `dashboard.index` |
| `/vehicles/` | GET | `vehicles.list` |
| `/vehicle-types/` | GET | `vehicle_types.list` |
| `/vehicle-types/new` | POST | `vehicle_types.create` |
| `/vehicle-types/<id>/delete` | POST | `vehicle_types.delete` |
| `/vehicles/new` | GET,POST | `vehicles.create` |
| `/vehicles/<id>/` | GET | `vehicles.detail` |
| `/vehicles/<id>/edit` | GET,POST | `vehicles.edit` |
| `/vehicles/<id>/delete` | POST | `vehicles.delete` |
| `/trips/` | GET | `trips.list` |
| `/trips/new` | GET,POST | `trips.create` |
| `/trips/<id>/` | GET | `trips.detail` |
| `/trips/<id>/edit` | GET,POST | `trips.edit` |
| `/trips/<id>/start` | POST | `trips.start` |
| `/trips/<id>/complete` | POST | `trips.complete` |
| `/trips/<id>/cancel` | POST | `trips.cancel` |
| `/trips/<id>/delete` | POST | `trips.delete` |
| `/drivers/` | GET | `drivers.list` |
| `/drivers/new` | GET,POST | `drivers.create` |
| `/drivers/<id>/` | GET | `drivers.detail` |
| `/drivers/<id>/edit` | GET,POST | `drivers.edit` |
| `/drivers/<id>/delete` | POST | `drivers.delete` |
| `/more/` | GET | `more.index` |
| `/fuel/` | GET | `fuel.list` |
| `/fuel/new` | GET,POST | `fuel.create` |
| `/fuel/<id>/edit` | GET,POST | `fuel.edit` |
| `/fuel/<id>/delete` | POST | `fuel.delete` |
| `/maintenance/` | GET | `maintenance.list` |
| `/maintenance/new` | GET,POST | `maintenance.create` |
| `/maintenance/<id>/` | GET | `maintenance.detail` |
| `/maintenance/<id>/edit` | GET,POST | `maintenance.edit` |
| `/maintenance/<id>/delete` | POST | `maintenance.delete` |
| `/expenses/` | GET | `expenses.list` |
| `/expenses/new` | GET,POST | `expenses.create` |
| `/expenses/<id>/edit` | GET,POST | `expenses.edit` |
| `/expenses/<id>/delete` | POST | `expenses.delete` |
| `/projects/` | GET | `projects.list` |
| `/projects/new` | GET,POST | `projects.create` |
| `/projects/<id>/` | GET | `projects.detail` (cost report, print/CSV) |
| `/projects/<id>/edit` | GET,POST | `projects.edit` |
| `/projects/<id>/delete` | POST | `projects.delete` |
| `/projects/<id>/csv` | GET | `projects.download_csv` |
| `/reports/` | GET | `reports.index` (→ monthly) |
| `/reports/monthly/` | GET | `reports.monthly` (print/CSV) |
| `/reports/monthly/csv` | GET | `reports.monthly_csv` |
| `/auth/login` | GET,POST | `auth.login` |
| `/auth/logout` | POST | `auth.logout` |
| `/auth/password` | GET,POST | `auth.change_password` |
| `/users/` | GET | `users.list` (admin) |
| `/users/new` | GET,POST | `users.create` (admin) |
| `/users/<id>/edit` | GET,POST | `users.edit` (admin) |
| `/users/<id>/password` | POST | `users.reset_password` (admin) |
| `/users/<id>/delete` | POST | `users.delete` (admin) |

## Project layout

```
app.py              entry point (flask --app app.py)
wsgi.py             production entry (gunicorn wsgi:app)
.flaskenv            FLASK_APP for the flask CLI
config.py           Config / DevConfig / TestConfig / ProdConfig
extensions.py       SQLAlchemy (db) + Flask-Migrate (migrate) instances
app/
  __init__.py       application factory: config, security, CLI, blueprints, shell context
  security.py       login manager, CSRF, global auth + role guards, _CurrentUser
  cli.py            seed-db / init-db / create-user / backup-db commands
  blueprints/       HTTP layer: auth, users, dashboard, vehicles, trips, drivers,
                    fuel, maintenance, expenses, projects, reports, more
  models/           Vehicle, TripLog, FuelLog, MaintenanceLog, Driver, Expense,
                    Project, User + timestamp base
  services/         business logic; raise ValueError on rule violations
  templates/        Jinja2: base, index, per-entity pages, partials, errors, auth/, users/
  static/           css/style.css (layout + components), js/app.js (minimal)
migrations/         Alembic revisions (flask db upgrade)
tests/              pytest suite: services, routes, models, CLI, seed, migrations,
                    projects, reports, hardening, auth, security (CSRF)
```

## Configuration

- `SECRET_KEY` — env var; the default `dev-secret-change-me` is for development
  only. In `production` the app refuses to boot unless it is set to a unique
  value of at least 32 characters.
- `DATABASE_URL` — env var; overrides the SQLite location. The default is
  `instance/vms.db` in **every** environment (development and production used
  to disagree, so a production boot without this var opened a second, empty
  database and failed on the first write).
- `TRUSTED_PROXY_HOPS` — env var; default `0`. How many reverse-proxy hops are
  trusted to set `X-Forwarded-*`. See Deployment → Proxies.
- `FLASK_CONFIG` — `development` (default), `testing`, or `production`.
- `CURRENCY` / `CURRENCY_SYMBOL` — env vars controlling how every cost field is
  displayed (defaults `USD` / `$`). Costs are stored as plain numbers; changing
  these changes the label only, never the stored values.
- `APP_TIMEZONE` — env var; default `Africa/Mogadishu`. The company's own wall
  clock, used for any "now" the app invents on a user's behalf: starting a trip
  with no start time, or completing one with no end time. It must match the
  time users type into forms, which are local wall-clock time — reading UTC
  instead put that fallback three hours behind the start_time it was about to
  be compared against, so same-shift trips could not be completed. Audit
  stamps (`created_at`/`updated_at`) stay on UTC, since they are never
  compared against entered times.
- **Trip status renders in Somali** via the `trip_status` template filter:
  `planned` → *isku diyaarin bixit*, `in_progress` → *baxay*, `completed` →
  *dhameystiray*, `cancelled` → *lajoojiyay*. Labels live in
  `TRIP_STATUS_LABELS` (`app/models/trip.py`) and are display-only — the DB
  keeps the English enum, which is what `?status=` filtering and the badge CSS
  classes key off. The same applies to the filter and form dropdowns: English
  `value`, Somali label.
- `flask run` / `app.run(debug=True)` starts a **development server**; use a
  production WSGI server for deployments.

## Analytics

Two rollups computed from data the fleet already records — no extra input
required of the user.

**Fuel efficiency (km/L)** — `fuel_service.fuel_efficiency()`. Uses the
fill-to-fill (tank) method: between two consecutive fill-ups on a vehicle, the
distance is `odometer₂ − odometer₁` and the fuel burned is the liters added at
the second fill (both tanks were full at each end). A pair is skipped when
either odometer is missing, unchanged, or went backwards — none of those yield
a trustworthy distance.

The headline figure is a **weighted** average (`total km ÷ total liters`), not
a mean of ratios, so one 2,000 km interval outweighs one 20 km interval.
Rendered on the Fuel page (fleet average + a per-vehicle table) and in the
vehicle-detail stats strip. A vehicle with fewer than two comparable readings
shows no figure rather than a misleading `0.0`.

**Trip cost** — `trip_service.trip_cost()`. Sums fuel and maintenance booked
to the trip's vehicle while the trip ran (window = start date → end date,
inclusive both ends), then divides by distance for a cost-per-km figure.
`distance_km` is primary; if it is absent the odometer difference is used.

- **Open trips** (no `end_time`, not yet completed/cancelled) are priced up to
  today and flagged `(open)` / `(so far)` — a running estimate.
- **Terminal trips with a missing `end_time`** are clamped to their start day,
  so a cancelled trip never sweeps up fill-ups from weeks later.
- **Other `Expense` records are excluded by design**: office rent or fleet
  insurance landing in the window is a period cost, not a cost caused by these
  kilometres. The Expenses page reports those separately, so nothing is
  double-counted.

## Projects & reports

Built for construction costing: every fuel log, trip, maintenance record and
expense can optionally be booked to a **Project** (a job site), so the app can
answer *"what did the Ring Road job actually cost?"*.

- **Projects** (`/projects/`) carry name, auto-issued `PRJ-0001`-style code,
  client, location, dates, status and notes. The link is **optional on every
  record** — office overhead and quick yard entries belong to no job, and
  nothing blocks saving without one. All four FKs are `ON DELETE SET NULL`
  (same reasoning as expenses on a vehicle: the money was spent, so the record
  survives); **deleting a project is refused while records still link to it**,
  so cost history is never stripped by accident.
- **Per-project cost report** (`/projects/<id>/`) rolls up fuel (total +
  liters), maintenance, other expenses and trip distance for the project over
  an optional date window, with a grand total and cost-per-km. It is
  **print-friendly** (browser Print → Save as PDF hides the chrome) and has a
  **CSV download** with one row per record plus totals.
- **Monthly summary** (`/reports/monthly/`) — pick any month: fleet costs per
  vehicle (fuel / maintenance / expenses side by side), expenses by category,
  trip count, fleet-wide costs that name no vehicle, and a grand total.
  Also print-friendly with a CSV download.
- Both reports sit behind the same auth/role guards as everything else:
  viewers can read and export, only operators/admins record data.

## Frontend / responsive behaviour

The UI is a server-rendered Flask/Jinja2 app with hand-written CSS
(`app/static/css/style.css`) — no frontend framework, no build step.

- **Desktop (>900px):** fixed sidebar navigation; tabular data renders as real
  `<table>` elements, which read well on a large screen.
- **Tablet/phone (≤900px):** the sidebar is replaced by a fixed **bottom
  navigation bar** for one-handed use, and the main content drops its left
  margin.
- **Phone (≤640px):** tables are **converted to stacked cards**. Every data
  `<td>` carries a `data-label="Column"` attribute; CSS hides the `<thead>` and
  reflows each row into a card, using `::before { content: attr(data-label) }`
  to print the column name above each value. Action buttons stack full-width.
  The same markup therefore serves both layouts — no duplicated DOM, and
  desktop keeps its tables.

Regression-guarded by `tests/test_mobile_ui.py` and `tests/test_mobile_cards.py`
(bottom-nav markup, PWA/manifest meta, and exact `data-label` coverage per page).

- **Dashboard KPI row** is four operational counts — **Total cars**, **Available**,
  **Under maintenance**, **Trips today** — each linking to the filtered list it
  summarizes and tinted by what it reports (neutral/green/amber/blue). The grid
  is 4-up on desktop, 2-up at ≤900px, 1-up at ≤380px. **Money is deliberately
  absent**: cost totals belong to the fuel, maintenance and expense pages, which
  each total their own figures. Keeping the dashboard to counts means it can
  never disagree with those pages about a number.
- **"Trips today"** counts trips *active* today (`trip_service.trips_active_on()`),
  not merely trips *starting* today: started on/before today and not yet finished,
  cancelled excluded. A trip spanning midnight counts on both days. Unfinished
  trips drop off the count on their own once today moves past them — no
  background job to expire stale rows.

## Testing

```bash
python -m pytest -q
```

## Design notes

- Application factory (`create_app`) in `app/__init__.py`; config selected by
  `FLASK_CONFIG` (defaults to `development`).
- Service layer raises `ValueError`; blueprints catch it, flash the message and
  redirect back to the form. `LookupError` becomes a 404.
- Models are context-free: no request/session coupling, validation lives in
  services.
- `seed-db` writes models directly (by design) so seed data can be laid out
  consistently (odometers, dates, distributions) without service-rule loops.
- Schema changes go through Flask-Migrate (`flask db upgrade`); `init-db`
  (`db.create_all()`) is the legacy fallback and a no-op on migrated databases.
- **Drivers replace typed names.** A trip no longer asks for a free-text driver
  name; it posts a `driver_id` chosen from registered drivers. `trip_log` keeps
  both `driver_id` (FK, `ON DELETE SET NULL`) and a snapshotted `driver_name`,
  so trip history survives a driver being renamed or deleted. Every driver is
  issued a unique `card_code` (auto-assigned as `DRV-0001` when left blank).
- **Expenses are separate from fuel and maintenance.** Fuel and maintenance keep
  their own specialised logs (liters, cost-per-litre, odometer, next-due-date).
  `expense` captures the remaining fleet costs — insurance, registration, wages,
  parking, tolls, washing, fines, office overhead, parts. `vehicle_id` is
  **optional**, so fleet-wide costs (office rent, fleet insurance) can be
  recorded without a vehicle. The FK is `ON DELETE SET NULL`: retiring a vehicle
  must not erase money that was actually spent, so the expense record survives
  with a nulled link. The Expenses page reports it as its own total rather
  than folding it into fuel/maintenance, so no cost is double-counted.
- **Every route is authenticated by default.** `app/security.py` installs a
  single `before_request` guard that redirects anonymous requests to
  `/auth/login`, so a newly added endpoint is protected unless it is explicitly
  added to `PUBLIC_ENDPOINTS` (only `static` and `auth.login`). Forgetting to
  protect a route is impossible; forgetting to *expose* one is deliberate. The
  same guard enforces roles: `viewer` may read but every POST/PUT/PATCH/DELETE
  returns 403, and the `users` blueprint (account management) requires `admin`.
  Passwords are hashed with Werkzeug's scrypt; login failures return one
  indistinguishable message for wrong-password and unknown-username (no account
  enumeration) and are throttled after `MAX_ATTEMPTS` from the same source.
- **CSRF is enforced by Flask-WTF** on all 20 POST forms. Its hook is registered
  *after* the auth guard, so an anonymous POST lands on the login page (302)
  rather than a bare 400, while any request that clears auth is still
  token-checked before reaching a view. `TestConfig` disables it (Flask-WTF's
  documented test setting) — `tests/test_security.py` re-enables it on a
  purpose-built app to prove missing, forged and cross-session tokens are all
  rejected and that a token scraped from a rendered form is accepted.
- Mobile tab bar is capped at five items (Home, Vehicles, Trips, Fuel, More);
  Maintenance and Drivers are reached through `/more/` so tap targets stay
  comfortably large on a phone. The desktop sidebar lists all sections.
- Debt register: **FIXED** — deprecated `datetime.utcnow` replaced by a naive-UTC
  helper (suite runs clean under `-W error::DeprecationWarning`); `migrations/env.py`
  prefers `.engine` over the deprecated `get_engine()`; form dropdowns use a single
  lightweight query instead of a paginated COUNT. No known debt outstanding.
