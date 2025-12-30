#!/usr/bin/env python3
"""
sync_wp_to_bmlt_v4.py

WordPress (nasuomi.org /wp-json/wp/v2/kokoukset) -> BMLT Admin API v4 importer.

Upgrades included:
- Periodic-run friendly: persistent geocode cache + run state under DATA_DIR (/data by default)
- Nominatim-friendly: caching + polite delay
- BMLT validations handled:
  - startTime/duration format HH:MM
  - day range 0..6
  - venueType integer (1/2/3)
  - comments truncated to 512 chars
  - formatIds filtered to only valid IDs from /formats
  - in-person requires street + (municipality/city or postal) + province (default BMLT_DEFAULT_PROVINCE)
  - virtual requires virtual link or phone; otherwise skip with reason
- Location field naming: send BOTH camelCase and snake_case variants to match mixed validator builds
- Better geocode input cleanup to reduce failures (strip parentheses, normalize separators)

Environment variables:
  WP_BASE (default: https://www.nasuomi.org)
  BMLT_BASE_URL (default: http://127.0.0.1)  [must include scheme]
  BMLT_ADMIN_USER / BMLT_ADMIN_PASS (required)
  BMLT_SERVICE_BODY_ID (default: 1)

  BMLT_DEFAULT_LAT / BMLT_DEFAULT_LON (defaults: Helsinki center)
  BMLT_ALLOW_FALLBACK_COORDS (0/1) (default 0)  - if 1, use default coords when geocoding fails (in-person)
  BMLT_DEFAULT_PROVINCE (default: Uusimaa)

  DATA_DIR (default: /data) - persists caches/state across runs
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urljoin

# ----------------------------
# Configuration
# ----------------------------

WP_BASE = os.environ.get("WP_BASE", "https://www.nasuomi.org").strip()
WP_ENDPOINT = "/wp-json/wp/v2/kokoukset"
WP_PER_PAGE = 100

BMLT_BASE_URL = os.environ.get("BMLT_BASE_URL", "http://127.0.0.1").strip()
BMLT_API_PREFIX = "/api/v1"
BMLT_USER = os.environ.get("BMLT_ADMIN_USER")
BMLT_PASS = os.environ.get("BMLT_ADMIN_PASS")
SERVICE_BODY_ID = int(os.environ.get("BMLT_SERVICE_BODY_ID", "1"))

DEFAULT_LAT = float(os.environ.get("BMLT_DEFAULT_LAT", "60.1699"))
DEFAULT_LON = float(os.environ.get("BMLT_DEFAULT_LON", "24.9384"))
ALLOW_FALLBACK_COORDS = os.environ.get("BMLT_ALLOW_FALLBACK_COORDS", "0") == "1"

DEFAULT_PROVINCE = os.environ.get("BMLT_DEFAULT_PROVINCE", "Uusimaa").strip() or "Uusimaa"

DATA_DIR = os.environ.get("DATA_DIR", "/data").strip() or "/data"
GEOCODE_CACHE_PATH = os.path.join(DATA_DIR, "geocode_cache.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

NOMINATIM = "https://nominatim.openstreetmap.org/search"

# BMLT Admin API v4 expectations
VENUE_IN_PERSON = 1
VENUE_VIRTUAL = 2
VENUE_HYBRID = 3

WEEKDAY_MAP = {
    "Sunnuntai": 0,
    "Maanantai": 1,
    "Tiistai": 2,
    "Keskiviikko": 3,
    "Torstai": 4,
    "Perjantai": 5,
    "Lauantai": 6,
}

# Map WP tokens -> BMLT format keys
FORMAT_KEY_MAP = {
    # Languages
    "suomi": "FIN",
    "englanti": "ENG",
    "venäjä": "L/R",  # ensure you actually have this key in BMLT formats
    # Types
    "Avoin": "O",
    "Suljettu": "C",
    "Meditaatio": "ME",
    "Puhujakokous": "So",
    "Askeltyökokous": "St",
    "Hybridi": "HY",
}

COMMENTS_MAX = 512

# ----------------------------
# Utilities
# ----------------------------


def require_scheme(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    raise ValueError(f"BMLT_BASE_URL must include http:// or https:// (got: {url!r})")


def http_json(method, url, data=None, headers=None, timeout=40):
    if headers is None:
        headers = {}
    headers = dict(headers)
    headers.setdefault("Accept", "application/json")

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}


def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def fetch_wp_all():
    items = []
    page = 1
    while True:
        qs = urlencode({"per_page": WP_PER_PAGE, "page": page})
        url = f"{WP_BASE}{WP_ENDPOINT}?{qs}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "wp-to-bmlt/2.7"},
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                break
            raise
        if not data:
            break
        items.extend(data)
        page += 1
    return items


def normalize_time(val: str) -> str:
    # BMLT expects HH:MM
    if not val:
        return ""
    s = str(val).strip().replace(".", ":")
    parts = s.split(":")
    try:
        if len(parts) == 1 and parts[0].isdigit():
            return f"{int(parts[0]):02d}:00"
        if len(parts) >= 2:
            h = int(parts[0])
            m = int(parts[1])
            return f"{h:02d}:{m:02d}"
    except Exception:
        return s
    return s


def duration_hm(minutes_val) -> str:
    # BMLT expects HH:MM
    try:
        mins = int(str(minutes_val).strip())
    except Exception:
        mins = 90
    if mins <= 0:
        mins = 90
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"


def strip_html_like(s: str) -> str:
    if not s:
        return ""
    txt = s.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    out = []
    in_tag = False
    for ch in txt:
        if ch == "<":
            in_tag = True
            continue
        if ch == ">":
            in_tag = False
            continue
        if not in_tag:
            out.append(ch)
    cleaned = "".join(out)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join([line.strip() for line in cleaned.split("\n") if line.strip()])
    return cleaned.strip()


def truncate_comments(s: str) -> str:
    if not s:
        return ""
    if len(s) <= COMMENTS_MAX:
        return s
    if COMMENTS_MAX <= 3:
        return s[:COMMENTS_MAX]
    return s[: COMMENTS_MAX - 1] + "…"


def split_tokens(v):
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if x]
    s = str(v)
    for sep in [",", " ja ", " & ", ";"]:
        s = s.replace(sep, ",")
    return [x.strip() for x in s.split(",") if x.strip()]


def is_virtual(obj: dict) -> bool:
    street = (obj.get("katuosoite") or "").lower()
    city = (obj.get("kaupunki") or "").lower()
    link = (obj.get("karttalinkki") or "").lower()
    if "internet" in city or "zoom" in street or "zoom" in link or "teams" in link:
        return True
    return False


def extract_first_url(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(https?://\S+)", text)
    if not m:
        return ""
    return m.group(1).rstrip(").,]")


def extract_phone_number(text: str) -> str:
    if not text:
        return ""
    t = strip_html_like(text)
    compact = t.replace(" ", "").replace("-", "")
    m = re.search(r"(\+\d{6,15}|\b0\d{6,15}\b)", compact)
    if m:
        return m.group(1)
    m2 = re.search(r"(\+\d[\d\s\-]{6,20}|\b0\d[\d\s\-]{6,20})", t)
    if m2:
        return re.sub(r"[^\d\+]", "", m2.group(1))
    return ""


def clean_geocode_query(street: str, postal: str, city: str, country: str) -> str:
    def _clean(s: str) -> str:
        if not s:
            return ""
        s = s.strip()
        s = re.sub(r"\([^)]*\)", "", s).strip()
        s = s.replace("/", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    street_c = _clean(street)
    postal_c = _clean(postal)
    city_c = _clean(city)
    country_c = _clean(country)
    parts = [p for p in [street_c, postal_c, city_c, country_c] if p]
    return ", ".join(parts)


def geocode_address(query: str):
    params = urlencode({"q": query, "format": "json", "limit": 1})
    url = f"{NOMINATIM}?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "wp-to-bmlt/2.7 (contact: admin@n/a)"},
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data:
        return None
    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon


def payload_fingerprint(payload: dict) -> str:
    relevant = dict(payload)
    relevant.pop("latitude", None)
    relevant.pop("longitude", None)
    blob = json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ----------------------------
# BMLT API helpers
# ----------------------------


def bmlt_login_token():
    require_scheme(BMLT_BASE_URL)
    if not BMLT_USER or not BMLT_PASS:
        print("Set BMLT_ADMIN_USER and BMLT_ADMIN_PASS.", file=sys.stderr)
        sys.exit(1)

    url = f"{BMLT_BASE_URL}{BMLT_API_PREFIX}/auth/token"
    data = {"username": BMLT_USER, "password": BMLT_PASS}

    # follow up to 3 redirects (handles proxy/front redirecting to /main_server, etc.)
    redirects = 0
    while True:
        try:
            resp = http_json("POST", url, data=data)
            break
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and redirects < 3:
                loc = e.headers.get("Location")
                if loc:
                    url = urljoin(url, loc)
                    redirects += 1
                    continue
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Login failed HTTP {e.code}: {body}") from None

    token = None
    if isinstance(resp, dict):
        token = resp.get("token") or resp.get("access_token") or resp.get("data", {}).get("token")
    if not token:
        raise RuntimeError(f"Login response did not contain a token. Response: {resp}")
    return token


def bmlt_get_formats(token: str):
    url = f"{BMLT_BASE_URL}{BMLT_API_PREFIX}/formats"
    headers = {"Authorization": f"Bearer {token}"}
    data = http_json("GET", url, headers=headers)
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected /formats response (expected list): {data}")

    by_key = {}
    allowed_ids = set()
    for f in data:
        fid = f.get("id")
        if fid is None:
            continue
        fid_int = int(fid)
        allowed_ids.add(fid_int)
        translations = f.get("translations") or []
        for tr in translations:
            k = (tr.get("key") or "").strip()
            if k:
                by_key[k] = fid_int
    return by_key, allowed_ids


def build_format_ids(obj: dict, format_key_to_id: dict):
    tokens = []
    tokens.extend(split_tokens(obj.get("rel_kokousmuodot")))
    tokens.extend(split_tokens(obj.get("rel_kokouskielet")))

    keys = []
    seen = set()

    if is_virtual(obj):
        if "VM" not in seen:
            keys.append("VM")
            seen.add("VM")

    for t in tokens:
        key = FORMAT_KEY_MAP.get(t)
        if key and key not in seen:
            keys.append(key)
            seen.add(key)

    ids = []
    missing_keys = []
    for k in keys:
        fid = format_key_to_id.get(k)
        if fid:
            ids.append(int(fid))
        else:
            missing_keys.append(k)
    return ids, missing_keys


def bmlt_create_meeting(token: str, payload: dict):
    url = f"{BMLT_BASE_URL}{BMLT_API_PREFIX}/meetings"
    headers = {"Authorization": f"Bearer {token}"}
    return http_json("POST", url, data=payload, headers=headers)


# ----------------------------
# Main
# ----------------------------


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    wp_items = fetch_wp_all()
    print(f"Fetched {len(wp_items)} meetings from WordPress.")

    token = bmlt_login_token()
    print("Authenticated to BMLT API.")

    format_key_to_id, allowed_format_ids = bmlt_get_formats(token)
    print(f"Loaded {len(format_key_to_id)} format keys from BMLT (mapped from translations[].key).")

    geocode_cache = load_json_file(GEOCODE_CACHE_PATH, {})
    state = load_json_file(STATE_PATH, {"fingerprints": {}, "last_run": None})
    fingerprints = state.get("fingerprints") if isinstance(state.get("fingerprints"), dict) else {}

    created = 0
    skipped = 0
    failed = 0
    skipped_reasons = {}
    failed_reasons = {}

    for obj in wp_items:
        wp_id = obj.get("id")
        title = obj.get("title", {}).get("rendered") or obj.get("slug") or f"WP-{wp_id}"

        weekday_fi = (obj.get("weekday") or "").strip()
        day = WEEKDAY_MAP.get(weekday_fi)
        start_time = normalize_time(obj.get("alkamisaika") or "")
        duration = duration_hm(obj.get("kesto") or "")

        if day is None or not start_time:
            skipped += 1
            skipped_reasons["missing_day_or_time"] = skipped_reasons.get("missing_day_or_time", 0) + 1
            continue

        street = (obj.get("katuosoite") or "").strip()
        postal = (obj.get("postinumero") or "").strip()
        city = (obj.get("kaupunki") or "").strip()
        country = (obj.get("maa") or "").strip() or "Finland"
        map_url = (obj.get("karttalinkki") or "").strip()

        comments_raw = strip_html_like(obj.get("lisatiedot") or "")
        comments = truncate_comments(comments_raw)

        virtual = is_virtual(obj)
        virtual_link = ""
        phone_number = ""
        if virtual:
            if map_url.startswith("http://") or map_url.startswith("https://"):
                virtual_link = map_url
            if not virtual_link:
                virtual_link = extract_first_url(comments_raw)
            phone_number = extract_phone_number(obj.get("lisatiedot") or "")
            if not virtual_link and not phone_number:
                skipped += 1
                skipped_reasons["virtual_missing_link_or_phone"] = skipped_reasons.get("virtual_missing_link_or_phone", 0) + 1
                print(f"SKIP wp_id={wp_id} virtual but missing link/phone for BMLT")
                continue

        if not virtual:
            if not street or (not city and not postal):
                skipped += 1
                skipped_reasons["in_person_missing_address"] = skipped_reasons.get("in_person_missing_address", 0) + 1
                print(f"SKIP wp_id={wp_id} in-person missing street or (city/postal)")
                continue

        venue_type = VENUE_VIRTUAL if virtual else VENUE_IN_PERSON
        if obj.get("rel_kokousmuodot") and "Hybridi" in str(obj.get("rel_kokousmuodot")):
            if street and (city or postal):
                venue_type = VENUE_HYBRID
            else:
                venue_type = VENUE_VIRTUAL

        format_ids, missing_format_keys = build_format_ids(obj, format_key_to_id)
        before = list(format_ids)
        format_ids = [fid for fid in format_ids if fid in allowed_format_ids]
        removed = [fid for fid in before if fid not in allowed_format_ids]

        if not format_ids and "FIN" in format_key_to_id:
            fin_id = format_key_to_id["FIN"]
            if fin_id in allowed_format_ids:
                format_ids = [fin_id]

        if not format_ids:
            skipped += 1
            skipped_reasons["no_valid_formats"] = skipped_reasons.get("no_valid_formats", 0) + 1
            print(f"SKIP wp_id={wp_id} no valid formats (missing_keys={missing_format_keys}, removed_ids={removed})")
            continue

        lat = DEFAULT_LAT
        lon = DEFAULT_LON

        if venue_type in (VENUE_IN_PERSON, VENUE_HYBRID):
            q = clean_geocode_query(street, postal, city, country)
            if q:
                if q in geocode_cache:
                    lat, lon = geocode_cache[q]
                else:
                    try:
                        res = geocode_address(q)
                        time.sleep(1.1)
                        if res:
                            lat, lon = res
                            geocode_cache[q] = (lat, lon)
                        else:
                            if not ALLOW_FALLBACK_COORDS:
                                skipped += 1
                                skipped_reasons["geocode_failed"] = skipped_reasons.get("geocode_failed", 0) + 1
                                print(f"SKIP wp_id={wp_id} could not geocode: {q}")
                                continue
                    except Exception as e:
                        if not ALLOW_FALLBACK_COORDS:
                            skipped += 1
                            skipped_reasons["geocode_error"] = skipped_reasons.get("geocode_error", 0) + 1
                            print(f"SKIP wp_id={wp_id} geocode error: {e}")
                            continue

        payload = {
            "serviceBodyId": SERVICE_BODY_ID,
            "name": strip_html_like(title),
            "day": day,
            "startTime": start_time,
            "duration": duration,
            "published": True,
            "venueType": venue_type,
            "latitude": lat,
            "longitude": lon,
            "formatIds": format_ids,
            "locationStreet": street,
            "locationCity": city,
            "locationPostalCode": postal,
            "locationCountry": country,
            "locationUrl": map_url,
            "location_street": street,
            "location_municipality": city,
            "location_postal_code": postal,
            "location_country": country,
            "location_url": map_url,
            "locationProvince": DEFAULT_PROVINCE,
            "location_province": DEFAULT_PROVINCE,
            "virtualMeetingLink": virtual_link,
            "virtual_meeting_link": virtual_link,
            "phoneMeetingNumber": phone_number,
            "phone_meeting_number": phone_number,
            "comments": comments,
            "externalId": f"wp:{wp_id}",
        }

        fp = payload_fingerprint(payload)
        if fingerprints.get(str(wp_id)) == fp:
            skipped += 1
            skipped_reasons["unchanged"] = skipped_reasons.get("unchanged", 0) + 1
            continue

        try:
            bmlt_create_meeting(token, payload)
            created += 1
            fingerprints[str(wp_id)] = fp

            if created % 25 == 0:
                print(f"Created {created} meetings so far...")

            if missing_format_keys:
                print(f"NOTE wp_id={wp_id} missing format keys in BMLT: {missing_format_keys}")
            if removed:
                print(f"NOTE wp_id={wp_id} removed invalid format IDs: {removed}")

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"FAILED wp_id={wp_id} HTTP {e.code}: {body}")
            failed += 1
            failed_reasons[str(e.code)] = failed_reasons.get(str(e.code), 0) + 1
        except Exception as e:
            print(f"FAILED wp_id={wp_id}: {e}")
            failed += 1
            failed_reasons["exception"] = failed_reasons.get("exception", 0) + 1

    save_json_file(GEOCODE_CACHE_PATH, geocode_cache)
    state_out = {
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "skipped_reasons": skipped_reasons,
        "failed_reasons": failed_reasons,
        "fingerprints": fingerprints,
    }
    save_json_file(STATE_PATH, state_out)

    print(f"Done. created={created} skipped={skipped} failed={failed}")
    if skipped_reasons:
        print(f"Skip reasons: {skipped_reasons}")
    if failed_reasons:
        print(f"Fail reasons: {failed_reasons}")


if __name__ == "__main__":
    main()

