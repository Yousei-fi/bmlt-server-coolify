# BMLT Root Server on Coolify

Docker Compose bundle for deploying BMLT Root Server (4.0.4) on Coolify. The BMLT code is tracked as a git submodule and configured via environment variables through `auto-config.inc.php`.

## Contents
- `bmlt-server/` – upstream BMLT server submodule (tag `4.0.4`)
- `Dockerfile` – php:8.3-apache image that installs PHP deps, builds UI assets, and serves `main_server`
- `docker-compose.yml` – web + MariaDB, no host ports (Coolify handles ingress)
- `auto-config.inc.php` – env-driven BMLT config placed beside `main_server`

## Prereqs
Clone with submodules:
```bash
git clone --recurse-submodules <this repo URL>
```
or, if already cloned:
```bash
git submodule update --init --recursive
```

## Environment variables (set in Coolify)
- `BMLT_DB_NAME` (required) – DB name
- `BMLT_DB_USER` (required) – DB user
- `BMLT_DB_PASSWORD` (required) – DB password
- `MARIADB_ROOT_PASSWORD` (required) – DB root password
- `BMLT_DB_HOST` (default `db`) – service name for the DB
- `BMLT_DB_PORT` (default `3306`)
- `BMLT_DB_PREFIX` (default `na`)
- `BMLT_BASE_URL` (optional) – canonical URL (surfaced as `APP_URL`)
- `BMLT_GOOGLE_MAPS_KEY` (optional) – set if using Google Maps
- `TZ` (default `Europe/Helsinki`)
- Optional tuning: `BMLT_REGION_BIAS`, `BMLT_DISTANCE_UNITS`, `BMLT_DEFAULT_LANGUAGE`, `BMLT_MAP_LONGITUDE`, `BMLT_MAP_LATITUDE`, `BMLT_MAP_ZOOM`, `BMLT_DEFAULT_DURATION`, `BMLT_DEFAULT_CLOSED_STATUS`, `BMLT_ENABLE_LANGUAGE_SELECTOR`

## How it works
- `auto-config.inc.php` consumes the env vars above and exposes the legacy `$db*`/`$gkey` settings expected by BMLT.
- Apache docroot is `/var/www/html/main_server/public`; the auto-config file lives at `/var/www/html/auto-config.inc.php`.
- `docker-compose.yml` keeps the DB internal (no `ports:`); Coolify maps your domain to the `web` service on port 80.
- Persistent data:
  - Database: `bmlt-db` volume (`/var/lib/mysql`)
  - App storage (logs/uploads/cache): `bmlt-web-storage` volume (`/var/www/html/main_server/storage`)

## Deploy on Coolify
1. Create an Application → GitHub → select this repo.
2. Build pack: Docker Compose; point to `docker-compose.yml`.
3. Set required env vars (`BMLT_DB_*`, `MARIADB_ROOT_PASSWORD`; optional `BMLT_BASE_URL`, `BMLT_GOOGLE_MAPS_KEY`, etc.).
4. Assign a domain to the `web` service (container port 80).
5. Deploy.

## First-run notes
- Schema/bootstrap: the container does not auto-run migrations. After first deploy, open the site (e.g., `/main_server`) and follow BMLT’s setup flow for 4.0.x, or run any required CLI install via Coolify “Execute command” on the `web` container once DB is ready.
- Admin login defaults remain as upstream (`serveradmin` / `change-this-password-first-thing`) until you change them in the UI.

## Local build/test (optional)
```bash
docker compose build
docker compose up -d
# visit http://localhost (Coolify will front this in production)
```

