from __future__ import annotations

import json
import os
import re
import sqlite3
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import datetime as dt
from dataclasses import dataclass
from html import unescape
from http import HTTPStatus
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
STATIC_DIR = BASE_DIR / "static"
ASSETS_DIR = BASE_DIR / "assets"
TRAY_SCRIPT_PATH = BASE_DIR / "scripts" / "start-tray.ps1"
RUTRACKER_BASE_URL = "https://rutracker.org/forum"
IMDB_BASE_URL = "https://www.imdb.com"
IMDB_SUGGESTION_BASE_URL = "https://v3.sg.media-imdb.com/suggestion"
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIMEDIA_FILE_PATH_BASE = "https://commons.wikimedia.org/wiki/Special:FilePath"
APP_VERSION = "1.5.1"
RUNTIME_STATUS_PATH = DATA_DIR / "runtime_status.json"
BACKGROUND_STALE_SECONDS = 180
METADATA_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RutrackerChecker/1.0"


def load_env(path: Path = BASE_DIR / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


ENV = load_env()


def config(name: str, default: str = "") -> str:
    return os.environ.get(name) or ENV.get(name) or default


def config_int(name: str, default: int) -> int:
    value = config(name, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def start_tray_if_background_enabled() -> None:
    if DB.get_setting("background_enabled", "1") != "1" or not TRAY_SCRIPT_PATH.exists():
        return
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-STA",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(TRAY_SCRIPT_PATH),
            ],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        print(f"Could not start tray icon: {exc}")


DEFAULT_MIN_SEEDERS = config_int("DEFAULT_MIN_SEEDERS", 5)
DEFAULT_MIN_SIZE_GB = config_int("DEFAULT_MIN_SIZE_GB", 5)
DEFAULT_CHECK_INTERVAL_MINUTES = config_int("DEFAULT_CHECK_INTERVAL_MINUTES", 360)
DEFAULT_REMINDER_INTERVAL_HOURS = config_int("DEFAULT_REMINDER_INTERVAL_HOURS", 12)
DEFAULT_BACKGROUND_ENABLED = config("DEFAULT_BACKGROUND_ENABLED", "1") != "0"
MAX_SEARCH_PAGES = config_int("MAX_SEARCH_PAGES", 3)
AUTO_SHUTDOWN_WHEN_IDLE = config("AUTO_SHUTDOWN_WHEN_IDLE", "1") != "0"
AUTO_SHUTDOWN_GRACE_SECONDS = config_int("AUTO_SHUTDOWN_GRACE_SECONDS", 45)
APP_HOST = config("APP_HOST", "127.0.0.1")
APP_PORT = config_int("APP_PORT", 9876)

SETTING_ENV = {
    "rutracker_username": "RUTRACKER_USERNAME",
    "rutracker_password": "RUTRACKER_PASSWORD",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "default_min_seeders": "DEFAULT_MIN_SEEDERS",
    "default_min_size_gb": "DEFAULT_MIN_SIZE_GB",
    "default_require_1080p": "DEFAULT_REQUIRE_1080P",
    "background_enabled": "DEFAULT_BACKGROUND_ENABLED",
    "check_interval_minutes": "DEFAULT_CHECK_INTERVAL_MINUTES",
    "reminder_interval_hours": "DEFAULT_REMINDER_INTERVAL_HOURS",
    "max_search_pages": "MAX_SEARCH_PAGES",
}

SETTING_DEFAULTS = {
    "rutracker_username": "",
    "rutracker_password": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "default_min_seeders": str(DEFAULT_MIN_SEEDERS),
    "default_min_size_gb": str(DEFAULT_MIN_SIZE_GB),
    "default_require_1080p": "1",
    "background_enabled": "1" if DEFAULT_BACKGROUND_ENABLED else "0",
    "check_interval_minutes": str(DEFAULT_CHECK_INTERVAL_MINUTES),
    "reminder_interval_hours": str(DEFAULT_REMINDER_INTERVAL_HOURS),
    "max_search_pages": str(MAX_SEARCH_PAGES),
}

SECRET_SETTINGS = {"rutracker_password", "telegram_bot_token"}


@dataclass(frozen=True)
class SearchResult:
    topic_id: str
    title: str
    url: str
    seeders: int
    resolution: str
    size_bytes: int = 0
    size_label: str = ""


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", "", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", "", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_resolution(title: str) -> str | None:
    normalized = title.lower()
    if re.search(r"\b(2160p?|4k|uhd)\b", normalized) or "3840x2160" in normalized:
        return "2160p"
    if re.search(r"\b1080[pi]?\b", normalized) or "1920x1080" in normalized:
        return "1080p"
    return None


def parse_int(value: str) -> int:
    match = re.search(r"\d[\d\s,.]*", strip_tags(value))
    if not match:
        return 0
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits or "0")


def parse_size(value: str) -> tuple[int, str]:
    text = strip_tags(value).replace("\xa0", " ")
    match = re.search(r"(\d+(?:[,.]\d+)?)\s*(TB|ТБ|GB|ГБ|MB|МБ)", text, flags=re.I)
    if not match:
        return 0, ""

    amount = float(match.group(1).replace(",", "."))
    unit = match.group(2).upper()
    multiplier = 1
    if unit in {"TB", "ТБ"}:
        multiplier = 1024**4
        label_unit = "TB"
    elif unit in {"GB", "ГБ"}:
        multiplier = 1024**3
        label_unit = "GB"
    else:
        multiplier = 1024**2
        label_unit = "MB"
    label = f"{amount:g} {label_unit}"
    return int(amount * multiplier), label


def parse_rutracker_results(html: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I | re.S)

    for row in rows:
        topic_match = re.search(r"viewtopic\.php\?t=(\d+)", row, flags=re.I)
        if not topic_match:
            continue

        topic_id = topic_match.group(1)
        link_pattern = (
            r'<a\b[^>]*href=["\'][^"\']*viewtopic\.php\?t='
            + re.escape(topic_id)
            + r'[^"\']*["\'][^>]*>(.*?)</a>'
        )
        title_match = re.search(link_pattern, row, flags=re.I | re.S)
        title = strip_tags(title_match.group(1)) if title_match else ""
        if not title:
            continue
        if topic_id == "101236" or title.lower() in {"помощь по поиску", "РїРѕРјРѕС‰СЊ РїРѕ РїРѕРёСЃРєСѓ"}:
            continue

        seed_match = re.search(
            r'<(?:td|b|span)\b[^>]*class=["\'][^"\']*(?:seed|seedmed)[^"\']*["\'][^>]*>(.*?)</(?:td|b|span)>',
            row,
            flags=re.I | re.S,
        )
        seeders = parse_int(seed_match.group(1)) if seed_match else 0
        if not seed_match:
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
            numeric_cells = [parse_int(cell) for cell in cells if parse_int(cell) > 0]
            if numeric_cells:
                seeders = max(numeric_cells[-3:] or numeric_cells)
        size_bytes, size_label = parse_size(row)
        resolution = parse_resolution(title)
        if not resolution:
            row_text = strip_tags(row)
            resolution = parse_resolution(row_text)

        results.append(
            SearchResult(
                topic_id=topic_id,
                title=title,
                url=f"{RUTRACKER_BASE_URL}/viewtopic.php?t={topic_id}",
                seeders=seeders,
                resolution=resolution or "",
                size_bytes=size_bytes,
                size_label=size_label,
            )
        )

    return results


def parse_next_page_url(html: str, current_url: str) -> str | None:
    for href, text in re.findall(
        r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        flags=re.I | re.S,
    ):
        label = strip_tags(text).lower()
        if "след" not in label:
            continue
        href = unescape(href)
        if "tracker.php" not in href:
            continue
        return urllib.parse.urljoin(current_url, href)
    return None


def quote_rutracker_query(query: str) -> str:
    return urllib.parse.quote_from_bytes(query.encode("cp1251", errors="ignore"))


def filter_results(
    results: list[SearchResult],
    min_seeders: int,
    min_size_gb: float = DEFAULT_MIN_SIZE_GB,
    require_1080p: bool = True,
) -> list[SearchResult]:
    min_size_bytes = int(max(0.0, float(min_size_gb)) * 1024**3)
    return [
        result
        for result in results
        if result.seeders >= min_seeders and result.size_bytes >= min_size_bytes
        and (not require_1080p or result.resolution in {"1080p", "2160p"})
    ]


def clean_external_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def normalize_imdb_url(value: Any) -> str:
    url = clean_external_url(value)
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc.lower().endswith("imdb.com"):
        return ""
    match = re.search(r"/title/(tt\d+)", parsed.path)
    if match:
        return f"{IMDB_BASE_URL}/title/{match.group(1)}/"
    return url


def imdb_title_id_from_url(value: Any) -> str:
    url = normalize_imdb_url(value)
    if not url:
        return ""
    match = re.search(r"/title/(tt\d+)", urllib.parse.urlparse(url).path)
    return match.group(1) if match else ""


def fetch_html(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": METADATA_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": METADATA_USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def extract_meta_content(html: str, names: tuple[str, ...]) -> str:
    for attr in ("property", "name"):
        for name in names:
            pattern = (
                rf'<meta\b(?=[^>]*\b{attr}=["\']{re.escape(name)}["\'])'
                r'(?=[^>]*\bcontent=["\']([^"\']+)["\'])[^>]*>'
            )
            match = re.search(pattern, html, flags=re.I | re.S)
            if match:
                return unescape(match.group(1)).strip()
    return ""


def normalize_metadata_query(value: str) -> str:
    text = unescape(str(value or "")).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def imdb_suggestion_key(value: str) -> str:
    normalized = normalize_metadata_query(value)
    if not normalized:
        return ""
    return urllib.parse.quote(normalized.replace(" ", "_"), safe="_")


def imdb_metadata_candidates(*values: str) -> list[str]:
    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = normalize_metadata_query(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    for value in values:
        base = normalize_metadata_query(value)
        if not base:
            continue
        add(base)
        words = base.split()
        if len(words) >= 3:
            year = words[-1] if re.fullmatch(r"(19|20)\d{2}", words[-1]) else ""
            if year:
                add(" ".join(words[:-1]))
                for index in range(1, len(words) - 1):
                    add(" ".join(words[:index] + words[index + 1 :]))
                for count in range(2, len(words) - 1):
                    add(" ".join(words[:count] + [year]))
            for count in range(2, min(len(words), 5)):
                add(" ".join(words[:count]))

    return candidates


def score_imdb_suggestion(item: dict[str, Any], search_text: str, expected_id: str = "") -> int:
    item_id = str(item.get("id") or "")
    if not re.fullmatch(r"tt\d+", item_id):
        return -1
    if expected_id and item_id == expected_id:
        return 10000

    item_title = normalize_metadata_query(str(item.get("l") or ""))
    search = normalize_metadata_query(search_text)
    if not item_title or not search:
        return 0

    item_words = set(item_title.split())
    search_words = set(search.split())
    common = len(item_words & search_words)
    score = common * 20
    if item_title == re.sub(r"\b(19|20)\d{2}\b", "", search).strip():
        score += 160
    if item_title == search:
        score += 220

    year = str(item.get("y") or "")
    if year and re.search(rf"\b{re.escape(year)}\b", search):
        score += 80
    if str(item.get("qid") or item.get("q") or "").lower() in {
        "movie",
        "feature",
        "tvmovie",
        "tv movie",
    }:
        score += 30
    if isinstance(item.get("i"), dict) and item["i"].get("imageUrl"):
        score += 20
    return score


def fetch_imdb_suggestion_metadata(key: str, search_text: str, expected_id: str = "") -> dict[str, str]:
    if not key:
        return {"imdb_url": "", "poster_url": ""}
    first = key[0].lower()
    if not first.isalnum():
        return {"imdb_url": "", "poster_url": ""}

    payload = fetch_json(f"{IMDB_SUGGESTION_BASE_URL}/{first}/{key}.json")
    rows = payload.get("d", []) if isinstance(payload, dict) else []
    best: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = score_imdb_suggestion(row, search_text, expected_id=expected_id)
        if score > best_score:
            best = row
            best_score = score

    if not best or best_score < 0:
        return {"imdb_url": "", "poster_url": ""}

    item_id = str(best.get("id") or "")
    image = best.get("i") if isinstance(best.get("i"), dict) else {}
    return {
        "imdb_url": f"{IMDB_BASE_URL}/title/{item_id}/",
        "poster_url": clean_external_url(image.get("imageUrl")),
        "_score": str(best_score),
    }


def wikimedia_file_url(filename: str) -> str:
    name = str(filename or "").strip().replace(" ", "_")
    if not name:
        return ""
    return clean_external_url(
        f"{WIKIMEDIA_FILE_PATH_BASE}/{urllib.parse.quote(name, safe='')}"
    )


def wikidata_claim_value(claim: dict[str, Any]) -> Any:
    mainsnak = claim.get("mainsnak") if isinstance(claim, dict) else {}
    datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, dict) else {}
    return datavalue.get("value") if isinstance(datavalue, dict) else None


def wikidata_image_from_entity(entity: dict[str, Any]) -> str:
    claims = entity.get("claims") if isinstance(entity, dict) else {}
    image_claims = claims.get("P18") if isinstance(claims, dict) else []
    for claim in image_claims if isinstance(image_claims, list) else []:
        value = wikidata_claim_value(claim)
        if isinstance(value, str):
            url = wikimedia_file_url(value)
            if url:
                return url
    return ""


def wikidata_imdb_id_from_entity(entity: dict[str, Any]) -> str:
    claims = entity.get("claims") if isinstance(entity, dict) else {}
    imdb_claims = claims.get("P345") if isinstance(claims, dict) else []
    for claim in imdb_claims if isinstance(imdb_claims, list) else []:
        value = wikidata_claim_value(claim)
        if isinstance(value, str) and re.fullmatch(r"tt\d+", value):
            return value
    return ""


def fetch_wikidata_entity(entity_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"Q\d+", entity_id or ""):
        return {}
    query = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": entity_id,
            "props": "claims",
            "format": "json",
        }
    )
    payload = fetch_json(f"{WIKIDATA_API_URL}?{query}")
    entities = payload.get("entities", {}) if isinstance(payload, dict) else {}
    entity = entities.get(entity_id) if isinstance(entities, dict) else {}
    return entity if isinstance(entity, dict) else {}


def fetch_wikidata_metadata_by_imdb_id(imdb_id: str) -> dict[str, str]:
    if not re.fullmatch(r"tt\d+", imdb_id or ""):
        return {"imdb_url": "", "poster_url": ""}
    sparql = (
        'SELECT ?item ?image WHERE { '
        f'?item wdt:P345 "{imdb_id}". '
        "OPTIONAL { ?item wdt:P18 ?image. } "
        "} LIMIT 1"
    )
    query = urllib.parse.urlencode({"format": "json", "query": sparql})
    payload = fetch_json(f"{WIKIDATA_SPARQL_URL}?{query}")
    results = payload.get("results", {}) if isinstance(payload, dict) else {}
    bindings = results.get("bindings", []) if isinstance(results, dict) else []
    if not bindings:
        return {"imdb_url": "", "poster_url": ""}
    first = bindings[0] if isinstance(bindings[0], dict) else {}
    image = first.get("image") if isinstance(first, dict) else {}
    poster_url = clean_external_url(image.get("value")) if isinstance(image, dict) else ""
    return {
        "imdb_url": f"{IMDB_BASE_URL}/title/{imdb_id}/",
        "poster_url": poster_url,
    }


def score_wikidata_search_result(
    row: dict[str, Any],
    search_text: str,
    expected_imdb_id: str = "",
) -> int:
    label = normalize_metadata_query(str(row.get("label") or ""))
    description = normalize_metadata_query(str(row.get("description") or ""))
    search = normalize_metadata_query(search_text)
    if not label or not search:
        return -1

    score = 0
    if label == search:
        score += 220
    if label == re.sub(r"\b(19|20)\d{2}\b", "", search).strip():
        score += 140
    score += len(set(label.split()) & set(search.split())) * 18
    if re.search(r"\b(film|movie|television film|animated film)\b", description):
        score += 50
    year_match = re.search(r"\b(19|20)\d{2}\b", search)
    if year_match and year_match.group(1) in description:
        score += 35
    if expected_imdb_id and expected_imdb_id in str(row):
        score += 1000
    return score


def fetch_wikidata_metadata_by_title(
    title: str,
    query: str = "",
    expected_imdb_id: str = "",
) -> dict[str, str]:
    best: dict[str, str] = {"imdb_url": "", "poster_url": ""}
    best_score = -1
    for candidate in imdb_metadata_candidates(title, query):
        params = urllib.parse.urlencode(
            {
                "action": "wbsearchentities",
                "search": candidate,
                "language": "en",
                "format": "json",
                "limit": "5",
            }
        )
        payload = fetch_json(f"{WIKIDATA_API_URL}?{params}")
        rows = payload.get("search", []) if isinstance(payload, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            entity_id = str(row.get("id") or "")
            entity = fetch_wikidata_entity(entity_id)
            poster_url = wikidata_image_from_entity(entity)
            imdb_id = wikidata_imdb_id_from_entity(entity)
            if expected_imdb_id and imdb_id and imdb_id != expected_imdb_id:
                continue
            score = score_wikidata_search_result(row, candidate, expected_imdb_id)
            if poster_url:
                score += 25
            if imdb_id:
                score += 25
            if score > best_score and (poster_url or imdb_id):
                best_score = score
                best = {
                    "imdb_url": f"{IMDB_BASE_URL}/title/{imdb_id}/" if imdb_id else "",
                    "poster_url": poster_url,
                }
    return best


def fetch_wikidata_metadata(title: str, imdb_url: str = "", query: str = "") -> dict[str, str]:
    imdb_id = imdb_title_id_from_url(imdb_url)
    if imdb_id:
        metadata = fetch_wikidata_metadata_by_imdb_id(imdb_id)
        if metadata.get("poster_url"):
            return metadata
    return fetch_wikidata_metadata_by_title(title, query, imdb_id)


def discover_imdb_url(title: str) -> str:
    metadata = fetch_movie_metadata(title)
    return metadata.get("imdb_url", "")


def fetch_movie_metadata(title: str, imdb_url: str = "", query: str = "") -> dict[str, str]:
    title_id = imdb_title_id_from_url(imdb_url)
    if title_id:
        metadata = fetch_imdb_suggestion_metadata(title_id, title_id, expected_id=title_id)
        if metadata.get("poster_url"):
            return {
                "imdb_url": metadata.get("imdb_url", ""),
                "poster_url": metadata.get("poster_url", ""),
            }

    best: dict[str, str] = {"imdb_url": normalize_imdb_url(imdb_url), "poster_url": ""}
    best_score = -1
    for candidate in imdb_metadata_candidates(title, query):
        key = imdb_suggestion_key(candidate)
        metadata = fetch_imdb_suggestion_metadata(key, candidate)
        if metadata.get("imdb_url"):
            score = int(metadata.get("_score") or 0)
            if score > best_score:
                best = metadata
                best_score = score
    if not best.get("poster_url"):
        fallback = fetch_wikidata_metadata(title, best.get("imdb_url") or imdb_url, query)
        if fallback.get("poster_url") or fallback.get("imdb_url"):
            best = {
                "imdb_url": fallback.get("imdb_url") or best.get("imdb_url", ""),
                "poster_url": fallback.get("poster_url") or best.get("poster_url", ""),
            }
    return {
        "imdb_url": best.get("imdb_url", ""),
        "poster_url": best.get("poster_url", ""),
    }


def refresh_item_metadata(db: "Database", item_id: int) -> dict[str, Any]:
    item = db.get_item(item_id)
    if item is None:
        raise KeyError("item not found")

    metadata_error = ""
    try:
        metadata = fetch_movie_metadata(
            str(item.get("title") or item.get("query") or ""),
            str(item.get("imdb_url") or ""),
            str(item.get("query") or ""),
        )
        item = db.update_item_metadata(
            item_id,
            metadata.get("imdb_url", ""),
            metadata.get("poster_url", ""),
        )
    except Exception as exc:
        metadata_error = str(exc)
        item = db.get_item(item_id)
        assert item is not None

    return {"item": item, "metadata_error": metadata_error}


def metadata_attempt_is_recent(value: str, now: dt.datetime, max_age_hours: int = 24) -> bool:
    parsed = parse_iso_datetime(value)
    return parsed is not None and now - parsed < dt.timedelta(hours=max_age_hours)


def refresh_missing_posters(db: "Database", limit: int = 20) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    refreshed = 0
    for item in db.list_items():
        if refreshed >= limit:
            break
        if str(item.get("poster_url") or "").strip():
            continue
        if metadata_attempt_is_recent(str(item.get("poster_updated_at") or ""), now):
            continue
        try:
            refresh_item_metadata(db, int(item["id"]))
            refreshed += 1
        except Exception as exc:
            print(f"Poster refresh failed for item {item.get('id')}: {exc}")
    return refreshed


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.init()

    def conn(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._local.connection = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def init(self) -> None:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                query TEXT NOT NULL,
                imdb_url TEXT NOT NULL DEFAULT '',
                poster_url TEXT NOT NULL DEFAULT '',
                poster_updated_at TEXT NOT NULL DEFAULT '',
                min_seeders INTEGER NOT NULL DEFAULT 5,
                min_size_gb REAL NOT NULL DEFAULT 5,
                require_1080p INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                topic_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                resolution TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                size_label TEXT NOT NULL DEFAULT '',
                seeders INTEGER NOT NULL DEFAULT 0,
                is_new INTEGER NOT NULL DEFAULT 1,
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(item_id, topic_id)
            );

            CREATE INDEX IF NOT EXISTS idx_results_item_new
                ON results(item_id, is_new);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.ensure_column(connection, "items", "imdb_url", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column(connection, "items", "poster_url", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column(connection, "items", "poster_updated_at", "TEXT NOT NULL DEFAULT ''")
        self.ensure_column(connection, "items", "min_size_gb", "REAL NOT NULL DEFAULT 5")
        self.ensure_column(connection, "items", "require_1080p", "INTEGER NOT NULL DEFAULT 1")
        self.ensure_column(connection, "results", "size_bytes", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column(connection, "results", "size_label", "TEXT NOT NULL DEFAULT ''")
        connection.commit()
        connection.close()

    @staticmethod
    def ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is not None:
            return str(row["value"])
        env_name = SETTING_ENV.get(key)
        if env_name:
            return config(env_name, SETTING_DEFAULTS.get(key, default))
        return SETTING_DEFAULTS.get(key, default)

    def get_setting_int(self, key: str, default: int) -> int:
        try:
            return int(self.get_setting(key, str(default)))
        except ValueError:
            return default

    def set_setting(self, key: str, value: str) -> None:
        self.conn().execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        self.conn().commit()

    def get_public_settings(self) -> dict[str, Any]:
        return {
            "rutracker_username": self.get_setting("rutracker_username"),
            "has_rutracker_password": bool(self.get_setting("rutracker_password")),
            "telegram_chat_id": self.get_setting("telegram_chat_id"),
            "has_telegram_bot_token": bool(self.get_setting("telegram_bot_token")),
            "default_min_seeders": self.get_setting_int("default_min_seeders", DEFAULT_MIN_SEEDERS),
            "default_min_size_gb": float(
                self.get_setting("default_min_size_gb", str(DEFAULT_MIN_SIZE_GB))
            ),
            "default_require_1080p": self.get_setting("default_require_1080p", "1") == "1",
            "background_enabled": self.get_setting("background_enabled", "1") == "1",
            "check_interval_minutes": self.get_setting_int(
                "check_interval_minutes", DEFAULT_CHECK_INTERVAL_MINUTES
            ),
            "reminder_interval_hours": self.get_setting_int(
                "reminder_interval_hours", DEFAULT_REMINDER_INTERVAL_HOURS
            ),
            "max_search_pages": self.get_setting_int("max_search_pages", MAX_SEARCH_PAGES),
        }

    def has_rutracker_credentials(self) -> bool:
        return bool(
            self.get_setting("rutracker_username").strip()
            and self.get_setting("rutracker_password").strip()
        )

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = set(SETTING_DEFAULTS)
        for key, raw_value in payload.items():
            if key not in allowed:
                continue
            if key in SECRET_SETTINGS and raw_value == "":
                continue
            value = str(raw_value).strip()
            if key in {"default_min_seeders", "check_interval_minutes", "reminder_interval_hours"}:
                value = str(max(0, int(value or "0")))
            if key == "background_enabled":
                value = "1" if raw_value in (True, "true", "1", "on", 1) else "0"
            if key == "max_search_pages":
                value = str(max(1, min(10, int(value or "1"))))
            if key == "default_min_size_gb":
                value = str(max(0.0, float(value or "0")))
            if key == "default_require_1080p":
                value = "1" if raw_value in (True, "true", "1", "on", 1) else "0"
            self.conn().execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )
        self.conn().commit()
        return self.get_public_settings()

    def list_items(self) -> list[dict[str, Any]]:
        rows = self.conn().execute(
            """
            SELECT
                i.*,
                COALESCE(SUM(CASE WHEN r.is_new = 1 THEN 1 ELSE 0 END), 0) AS new_count,
                MAX(r.first_seen_at) AS latest_result_at
            FROM items i
            LEFT JOIN results r ON r.item_id = i.id
            GROUP BY i.id
            ORDER BY i.updated_at DESC, i.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        row = self.conn().execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None

    def create_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or payload.get("title") or "").strip()
        title = str(payload.get("title") or query).strip()
        if not query:
            raise ValueError("query is required")
        if not title:
            title = query
        imdb_url = normalize_imdb_url(payload.get("imdb_url"))
        poster_url = clean_external_url(payload.get("poster_url"))
        min_seeders = int(
            payload.get("min_seeders") or self.get_setting_int("default_min_seeders", DEFAULT_MIN_SEEDERS)
        )
        min_size_gb = float(
            payload.get("min_size_gb")
            or self.get_setting("default_min_size_gb", str(DEFAULT_MIN_SIZE_GB))
        )
        require_1080p = 1 if payload.get(
            "require_1080p",
            self.get_setting("default_require_1080p", "1") == "1",
        ) else 0
        enabled = 1 if payload.get("enabled", True) else 0
        cursor = self.conn().execute(
            """
            INSERT INTO items
                (title, query, imdb_url, poster_url, poster_updated_at,
                 min_seeders, min_size_gb, require_1080p, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                query,
                imdb_url,
                poster_url,
                dt.datetime.now(dt.timezone.utc).isoformat() if poster_url else "",
                min_seeders,
                min_size_gb,
                require_1080p,
                enabled,
            ),
        )
        self.conn().commit()
        item = self.get_item(int(cursor.lastrowid))
        assert item is not None
        return item

    def update_item(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        item = self.get_item(item_id)
        if item is None:
            raise KeyError("item not found")

        query = str(payload.get("query", item["query"])).strip()
        title = str(payload.get("title", query)).strip() or query
        imdb_url = normalize_imdb_url(payload.get("imdb_url", item.get("imdb_url", "")))
        poster_url = clean_external_url(payload.get("poster_url", item.get("poster_url", "")))
        min_seeders = int(payload.get("min_seeders", item["min_seeders"]))
        min_size_gb = float(payload.get("min_size_gb", item["min_size_gb"]))
        require_1080p = 1 if payload.get("require_1080p", bool(item["require_1080p"])) else 0
        enabled = 1 if payload.get("enabled", bool(item["enabled"])) else 0
        if not query:
            raise ValueError("query is required")

        self.conn().execute(
            """
            UPDATE items
            SET title = ?, query = ?, imdb_url = ?, poster_url = ?,
                poster_updated_at = CASE
                    WHEN poster_url <> ? THEN ?
                    ELSE poster_updated_at
                END,
                min_seeders = ?, min_size_gb = ?, require_1080p = ?, enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                title,
                query,
                imdb_url,
                poster_url,
                poster_url,
                dt.datetime.now(dt.timezone.utc).isoformat() if poster_url else "",
                min_seeders,
                min_size_gb,
                require_1080p,
                enabled,
                item_id,
            ),
        )
        self.conn().commit()
        updated = self.get_item(item_id)
        assert updated is not None
        return updated

    def update_item_metadata(
        self,
        item_id: int,
        imdb_url: str,
        poster_url: str,
    ) -> dict[str, Any]:
        if self.get_item(item_id) is None:
            raise KeyError("item not found")
        imdb_url = normalize_imdb_url(imdb_url)
        poster_url = clean_external_url(poster_url)
        self.conn().execute(
            """
            UPDATE items
            SET imdb_url = COALESCE(NULLIF(?, ''), imdb_url),
                poster_url = COALESCE(NULLIF(?, ''), poster_url),
                poster_updated_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                imdb_url,
                poster_url,
                dt.datetime.now(dt.timezone.utc).isoformat(),
                item_id,
            ),
        )
        self.conn().commit()
        updated = self.get_item(item_id)
        assert updated is not None
        return updated

    def delete_item(self, item_id: int) -> None:
        self.conn().execute("DELETE FROM results WHERE item_id = ?", (item_id,))
        self.conn().execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.conn().commit()

    def reset_new(self, item_id: int) -> int:
        cursor = self.conn().execute(
            "UPDATE results SET is_new = 0 WHERE item_id = ? AND is_new = 1",
            (item_id,),
        )
        self.conn().commit()
        return cursor.rowcount

    def reset_new_that_fails_filter(
        self,
        item_id: int,
        min_seeders: int,
        min_size_gb: float,
        require_1080p: bool,
    ) -> int:
        min_size_bytes = int(max(0.0, float(min_size_gb)) * 1024**3)
        clauses = ["item_id = ?", "is_new = 1", "(seeders < ? OR size_bytes < ?"]
        params: list[Any] = [item_id, min_seeders, min_size_bytes]
        if require_1080p:
            clauses[-1] += " OR resolution NOT IN ('1080p', '2160p')"
        clauses[-1] += ")"
        cursor = self.conn().execute(
            f"UPDATE results SET is_new = 0 WHERE {' AND '.join(clauses)}",
            params,
        )
        self.conn().commit()
        return cursor.rowcount

    def count_new(self, item_id: int) -> int:
        row = self.conn().execute(
            "SELECT COUNT(*) AS count FROM results WHERE item_id = ? AND is_new = 1",
            (item_id,),
        ).fetchone()
        return int(row["count"] if row else 0)

    def list_results(self, item_id: int | None = None, only_new: bool = False) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if item_id is not None:
            where.append("item_id = ?")
            params.append(item_id)
        if only_new:
            where.append("is_new = 1")
        sql = "SELECT * FROM results"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY first_seen_at DESC, id DESC"
        rows = self.conn().execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def save_results(self, item_id: int, results: list[SearchResult]) -> list[dict[str, Any]]:
        new_rows: list[dict[str, Any]] = []
        connection = self.conn()
        for result in results:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO results
                    (item_id, topic_id, title, url, resolution, size_bytes, size_label, seeders, is_new)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    item_id,
                    result.topic_id,
                    result.title,
                    result.url,
                    result.resolution,
                    result.size_bytes,
                    result.size_label,
                    result.seeders,
                ),
            )
            if cursor.rowcount:
                row = connection.execute(
                    "SELECT * FROM results WHERE item_id = ? AND topic_id = ?",
                    (item_id, result.topic_id),
                ).fetchone()
                new_rows.append(dict(row))
            else:
                connection.execute(
                    """
                    UPDATE results
                    SET title = ?, url = ?, resolution = ?, size_bytes = ?, size_label = ?, seeders = ?,
                        last_seen_at = CURRENT_TIMESTAMP
                    WHERE item_id = ? AND topic_id = ?
                    """,
                    (
                        result.title,
                        result.url,
                        result.resolution,
                        result.size_bytes,
                        result.size_label,
                        result.seeders,
                        item_id,
                        result.topic_id,
                    ),
                )
        connection.commit()
        return new_rows


class RuTrackerClient:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self._logged_in = False
        self._identity: tuple[str, str] | None = None
        self._lock = threading.Lock()

    def credentials(self) -> tuple[str, str]:
        return (
            self.db.get_setting("rutracker_username"),
            self.db.get_setting("rutracker_password"),
        )

    def reset_session_if_needed(self, username: str, password: str) -> None:
        identity = (username, password)
        if self._identity == identity:
            return
        self.cookie_jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self._identity = identity
        self._logged_in = False

    def request(self, url: str, data: dict[str, str] | None = None) -> str:
        encoded_data = urllib.parse.urlencode(data).encode("cp1251") if data else None
        request = urllib.request.Request(
            url,
            data=encoded_data,
            headers={
                "User-Agent": "RutrackerChecker/1.0 (+local personal monitor)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            method="POST" if data else "GET",
        )
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                with self.opener.open(request, timeout=60) as response:
                    raw = response.read()
                    charset = response.headers.get_content_charset() or "cp1251"
                    return raw.decode(charset, errors="replace")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code < 500:
                    raise
                time.sleep(1 + attempt * 2)
            except (TimeoutError, socket.timeout, ConnectionResetError, urllib.error.URLError) as exc:
                last_error = exc
                time.sleep(1 + attempt * 2)
        assert last_error is not None
        raise last_error

    def login(self) -> None:
        username, password = self.credentials()
        if not username or not password:
            raise RuntimeError("RuTracker username and password are required in Settings")
        with self._lock:
            self.reset_session_if_needed(username, password)
            if self._logged_in:
                return
            html = self.request(
                f"{RUTRACKER_BASE_URL}/login.php",
                {
                    "login_username": username,
                    "login_password": password,
                    "login": "Вход",
                },
            )
            if "login.php" in html and "login_username" in html:
                raise RuntimeError("RuTracker login failed; check .env credentials")
            self._logged_in = True

    def search(self, query: str) -> list[SearchResult]:
        self.login()
        return self.search_one(query)

    def search_one(self, query: str) -> list[SearchResult]:
        url = f"{RUTRACKER_BASE_URL}/tracker.php?nm={quote_rutracker_query(query)}"
        max_pages = self.db.get_setting_int("max_search_pages", MAX_SEARCH_PAGES)
        all_results: dict[str, SearchResult] = {}
        seen_urls: set[str] = set()

        for _ in range(max_pages):
            if url in seen_urls:
                break
            seen_urls.add(url)
            html = self.request(url)
            if "login_username" in html and "login_password" in html:
                self._logged_in = False
                self.login()
                html = self.request(url)

            for result in parse_rutracker_results(html):
                all_results[result.topic_id] = result

            next_url = parse_next_page_url(html, url)
            if not next_url:
                break
            url = next_url

        return list(all_results.values())

    @staticmethod
    def search_url(query: str) -> str:
        return f"{RUTRACKER_BASE_URL}/tracker.php?nm={quote_rutracker_query(query)}"


class TelegramNotifier:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def enabled(self) -> bool:
        return bool(
            self.db.get_setting("telegram_bot_token")
            and self.db.get_setting("telegram_chat_id")
        )

    def send_new_results(self, item: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        if not self.enabled or not rows:
            return
        token = self.db.get_setting("telegram_bot_token")
        chat_id = self.db.get_setting("telegram_chat_id")

        lines = [f"{item['title']}: {len(rows)} new RuTracker result(s)"]
        for row in rows[:10]:
            lines.append(f"- {row['title']} ({row['seeders']} seeders) {row['url']}")
        if len(rows) > 10:
            lines.append(f"...and {len(rows) - 10} more")

        payload = urllib.parse.urlencode(
            {
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()


class CheckerService:
    def __init__(self, db: Database, client: RuTrackerClient, notifier: TelegramNotifier) -> None:
        self.db = db
        self.client = client
        self.notifier = notifier

    def check_item(self, item_id: int, notify: bool = True) -> dict[str, Any]:
        item = self.db.get_item(item_id)
        if not item:
            raise KeyError("item not found")

        raw_results = self.client.search(item["query"])
        filtered = filter_results(
            raw_results,
            int(item["min_seeders"]),
            float(item["min_size_gb"]),
            bool(item["require_1080p"]),
        )
        new_rows = self.db.save_results(item_id, filtered)
        pruned_new = self.db.reset_new_that_fails_filter(
            item_id,
            int(item["min_seeders"]),
            float(item["min_size_gb"]),
            bool(item["require_1080p"]),
        )
        if notify and new_rows:
            self.notifier.send_new_results(item, new_rows)

        return {
            "item": self.db.get_item(item_id),
            "raw": len(raw_results),
            "matched": len(filtered),
            "new": len(new_rows),
            "pruned_new": pruned_new,
            "pending_new": self.db.count_new(item_id),
            "new_results": new_rows,
            "search_url": RuTrackerClient.search_url(item["query"]),
        }

    def check_all(self, notify: bool = True) -> dict[str, Any]:
        summaries = []
        for item in self.db.list_items():
            if not item["enabled"]:
                continue
            try:
                summaries.append(self.check_item(int(item["id"]), notify=notify))
            except Exception as exc:
                summaries.append({"item": item, "error": str(exc), "new": 0, "matched": 0})
        return {
            "items_checked": len(summaries),
            "total_new": sum(int(summary.get("new", 0)) for summary in summaries),
            "total_pending_new": sum(
                int(summary.get("pending_new", 0)) for summary in summaries
            ),
            "results": summaries,
        }


DB = Database()
CLIENT = RuTrackerClient(DB)
NOTIFIER = TelegramNotifier(DB)
CHECKER = CheckerService(DB, CLIENT, NOTIFIER)


class UiSessionRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}
        self.had_session = False

    def heartbeat(self, session_id: str) -> int:
        now = time.monotonic()
        with self._lock:
            self.had_session = True
            self._sessions[session_id] = now
            self._prune_locked(now)
            return len(self._sessions)

    def active_count(self) -> int:
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            return len(self._sessions)

    def _prune_locked(self, now: float) -> None:
        stale_after = AUTO_SHUTDOWN_GRACE_SECONDS
        self._sessions = {
            session_id: last_seen
            for session_id, last_seen in self._sessions.items()
            if now - last_seen <= stale_after
        }


UI_SESSIONS = UiSessionRegistry()
SERVER: ThreadingHTTPServer | None = None
METADATA_BACKFILL_STARTED = False
METADATA_BACKFILL_LOCK = threading.Lock()


def request_shutdown(reason: str = "requested") -> None:
    print(f"Shutting down server: {reason}")

    def stop() -> None:
        time.sleep(0.1)
        if SERVER is not None:
            SERVER.shutdown()

    threading.Thread(target=stop, daemon=True).start()


def start_metadata_backfill() -> None:
    global METADATA_BACKFILL_STARTED
    with METADATA_BACKFILL_LOCK:
        if METADATA_BACKFILL_STARTED:
            return
        METADATA_BACKFILL_STARTED = True

    def worker() -> None:
        try:
            count = refresh_missing_posters(DB)
            if count:
                print(f"Poster backfill refreshed {count} item(s)")
        except Exception as exc:
            print(f"Poster backfill failed: {exc}")

    threading.Thread(target=worker, daemon=True).start()


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def read_runtime_status() -> dict[str, Any]:
    try:
        payload = json.loads(RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}

    now = dt.datetime.now(dt.timezone.utc)
    heartbeat_at = parse_iso_datetime(str(payload.get("last_heartbeat_at") or ""))
    background_enabled = DB.get_setting("background_enabled", "1") == "1"
    background_running = (
        background_enabled
        and heartbeat_at is not None
        and now - heartbeat_at <= dt.timedelta(seconds=BACKGROUND_STALE_SECONDS)
    )
    heartbeat_fresh = (
        heartbeat_at is not None
        and now - heartbeat_at <= dt.timedelta(seconds=BACKGROUND_STALE_SECONDS)
    )
    pending_count = sum(int(item.get("new_count") or 0) for item in DB.list_items())
    reminder_hours = DB.get_setting_int(
        "reminder_interval_hours", DEFAULT_REMINDER_INTERVAL_HOURS
    )
    last_reminder = parse_iso_datetime(DB.get_setting("last_pending_reminder_at"))
    next_reminder_at = None
    if background_enabled and pending_count > 0 and reminder_hours > 0:
        if last_reminder is None:
            next_reminder_at = now
        else:
            next_reminder_at = last_reminder + dt.timedelta(hours=reminder_hours)
            if next_reminder_at < now:
                next_reminder_at = now

    return {
        "server_running": True,
        "background_enabled": background_enabled,
        "background_running": background_running,
        "background_process_alive": heartbeat_fresh,
        "background_status_stale_seconds": BACKGROUND_STALE_SECONDS,
        "last_heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
        "last_check_at": payload.get("last_check_at"),
        "last_check_status": payload.get("last_check_status"),
        "last_check_message": payload.get("last_check_message"),
        "next_check_at": payload.get("next_check_at")
        if background_enabled and background_running
        else None,
        "check_interval_minutes": DB.get_setting_int(
            "check_interval_minutes", DEFAULT_CHECK_INTERVAL_MINUTES
        ),
        "pending_new_count": pending_count,
        "reminder_interval_hours": reminder_hours,
        "next_reminder_at": next_reminder_at.isoformat() if next_reminder_at else None,
    }


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "RutrackerChecker/1.0"

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            DB.close()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload: Any, status: int = 200) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, text: str, status: int = 200, content_type: str = "text/plain") -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data: bytes, status: int = 200, content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length == 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body or "{}")

    def handle_error(self, exc: Exception) -> None:
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        if isinstance(exc, ValueError):
            status = HTTPStatus.BAD_REQUEST
        elif isinstance(exc, KeyError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, (urllib.error.URLError, TimeoutError, RuntimeError)):
            status = HTTPStatus.BAD_GATEWAY
        self.send_json({"error": str(exc)}, int(status))

    def do_GET(self) -> None:
        try:
            request_path = urllib.parse.urlparse(self.path).path

            if request_path == "/":
                start_metadata_backfill()
                index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
                self.send_text(index, content_type="text/html")
                return

            if request_path == "/api/items":
                items = DB.list_items()
                public_settings = DB.get_public_settings()
                for item in items:
                    item["results"] = DB.list_results(int(item["id"]))
                    item["search_url"] = RuTrackerClient.search_url(item["query"])
                self.send_json(
                    {
                        "items": items,
                        "config": {
                            **public_settings,
                            "telegram_enabled": NOTIFIER.enabled,
                        },
                    }
                )
                return

            if request_path == "/api/settings":
                self.send_json(DB.get_public_settings())
                return

            if request_path == "/api/runtime":
                self.send_json(read_runtime_status())
                return

            if request_path == "/api/health":
                runtime = read_runtime_status()
                self.send_json(
                    {
                        "ok": True,
                        "version": APP_VERSION,
                        "background_enabled": runtime["background_enabled"],
                        "background_running": runtime["background_running"],
                        "active_ui_sessions": UI_SESSIONS.active_count(),
                        "auto_shutdown_when_idle": AUTO_SHUTDOWN_WHEN_IDLE,
                    }
                )
                return

            if request_path == "/favicon.ico":
                path = ASSETS_DIR / "app-icon.ico"
                if not path.exists():
                    self.send_json({"error": "not found"}, 404)
                    return
                self.send_bytes(path.read_bytes(), content_type="image/x-icon")
                return

            asset_match = re.match(r"^/assets/([A-Za-z0-9_.-]+)$", request_path)
            if asset_match:
                filename = asset_match.group(1)
                path = ASSETS_DIR / filename
                if not path.exists() or not path.is_file():
                    self.send_json({"error": "not found"}, 404)
                    return
                content_type = {
                    ".ico": "image/x-icon",
                    ".png": "image/png",
                }.get(path.suffix.lower(), "application/octet-stream")
                self.send_bytes(path.read_bytes(), content_type=content_type)
                return

            static_match = re.match(r"^/static/([A-Za-z0-9_.-]+)$", request_path)
            if static_match:
                filename = static_match.group(1)
                path = STATIC_DIR / filename
                if not path.exists():
                    self.send_json({"error": "not found"}, 404)
                    return
                content_type = "text/css" if filename.endswith(".css") else "application/javascript"
                self.send_text(path.read_text(encoding="utf-8"), content_type=content_type)
                return

            self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.handle_error(exc)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/items":
                if not DB.has_rutracker_credentials():
                    raise ValueError("Введите логин и пароль RuTracker перед добавлением фильма")
                self.send_json(DB.create_item(self.read_json()), 201)
                return

            if self.path == "/api/check-all":
                self.send_json(CHECKER.check_all(notify=True))
                return

            if self.path == "/api/heartbeat":
                payload = self.read_json()
                session_id = str(payload.get("session_id") or "").strip()
                if not session_id:
                    raise ValueError("session_id is required")
                self.send_json({"active_ui_sessions": UI_SESSIONS.heartbeat(session_id)})
                return

            if self.path == "/api/shutdown":
                self.send_json({"shutdown": True})
                request_shutdown("ui requested")
                return

            check_match = re.match(r"^/api/items/(\d+)/check$", self.path)
            if check_match:
                self.send_json(CHECKER.check_item(int(check_match.group(1)), notify=True))
                return

            metadata_match = re.match(r"^/api/items/(\d+)/refresh-metadata$", self.path)
            if metadata_match:
                self.send_json(refresh_item_metadata(DB, int(metadata_match.group(1))))
                return

            reset_match = re.match(r"^/api/items/(\d+)/reset-new$", self.path)
            if reset_match:
                count = DB.reset_new(int(reset_match.group(1)))
                self.send_json({"reset": count})
                return

            self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.handle_error(exc)

    def do_PATCH(self) -> None:
        try:
            if self.path == "/api/settings":
                settings = DB.update_settings(self.read_json())
                if settings["background_enabled"]:
                    start_tray_if_background_enabled()
                self.send_json(settings)
                return

            match = re.match(r"^/api/items/(\d+)$", self.path)
            if not match:
                self.send_json({"error": "not found"}, 404)
                return
            self.send_json(DB.update_item(int(match.group(1)), self.read_json()))
        except Exception as exc:
            self.handle_error(exc)

    def do_DELETE(self) -> None:
        try:
            match = re.match(r"^/api/items/(\d+)$", self.path)
            if not match:
                self.send_json({"error": "not found"}, 404)
                return
            DB.delete_item(int(match.group(1)))
            self.send_json({"deleted": True})
        except Exception as exc:
            self.handle_error(exc)


def scheduler_loop() -> None:
    next_run = time.monotonic() + DB.get_setting_int(
        "check_interval_minutes", DEFAULT_CHECK_INTERVAL_MINUTES
    ) * 60
    while True:
        time.sleep(5)
        interval_minutes = DB.get_setting_int(
            "check_interval_minutes", DEFAULT_CHECK_INTERVAL_MINUTES
        )
        background_enabled = DB.get_setting("background_enabled", "1") == "1"
        if not background_enabled or interval_minutes <= 0:
            next_run = time.monotonic() + 60
            continue
        if read_runtime_status()["background_running"]:
            next_run = time.monotonic() + 60
            continue
        if time.monotonic() < next_run:
            continue
        try:
            CHECKER.check_all(notify=True)
        except Exception as exc:
            print(f"Scheduled check failed: {exc}")
        next_run = time.monotonic() + interval_minutes * 60


def idle_shutdown_loop() -> None:
    if not AUTO_SHUTDOWN_WHEN_IDLE:
        return
    while True:
        time.sleep(5)
        if UI_SESSIONS.had_session and UI_SESSIONS.active_count() == 0:
            request_shutdown("no open UI tabs")
            return


def main() -> None:
    global SERVER
    scheduler = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler.start()
    idle_shutdown = threading.Thread(target=idle_shutdown_loop, daemon=True)
    idle_shutdown.start()
    httpd = ThreadingHTTPServer((APP_HOST, APP_PORT), RequestHandler)
    SERVER = httpd
    print(f"RuTracker Release Checker running at http://{APP_HOST}:{APP_PORT}")
    print("Press Ctrl+C to stop.")
    start_tray_if_background_enabled()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        DB.close()


if __name__ == "__main__":
    main()
