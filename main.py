from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import traceback
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_from_directory, url_for
from jinja2 import ChoiceLoader, FileSystemLoader, TemplateNotFound


APP_DIR = Path(__file__).resolve().parent
PACKAGED_DB_PATH = APP_DIR / "database" / "offlinedata.db"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("PRAAL_PORT", "5000"))
RUNTIME_LOG_NAME = "praal_startup.log"
STARTUP_NOTES: list[str] = []
UPDATE_CONFIG_NAME = "update_config.json"
UPDATE_STATE_NAME = "update_state.json"
RUNTIME_DATA_DIR_NAME = "data"
RUNTIME_UPDATES_DIR_NAME = "updates"
RUNTIME_OVERRIDE_DIR_NAME = "overrides"
VERSION_TOKEN_PATTERN = re.compile(r"\d+|[A-Za-z]+")
UPDATE_THREAD_LOCK = threading.Lock()
UPDATE_THREAD_STARTED = False
PACKAGED_UPDATE_CONFIG_PATH = APP_DIR / UPDATE_CONFIG_NAME


DISPLAY_ORDER = {
    "AMNESTY": [
        "collectorate_name",
        "name_of_owner",
        "vehicle_details",
        "chassis_number",
        "engine_capacity",
        "ono_no",
        "delivery_order_no",
        "delivery_order_date",
        "assessed_value",
        "total_amount_deposited",
    ],
    "84_TO_NOV22": [
        "cltcod",
        "betype",
        "mchnum",
        "mdat",
        "impnam",
        "item_description",
        "igm_no",
        "igm_index",
        "igm_year",
        "blno",
        "bldate",
    ],
    "JUL22_TO_OCT23": [
        "cltcod",
        "betype",
        "mchnum",
        "gd_no_complete",
        "gd_date",
        "bl_no",
        "bl_date",
        "igm_no",
        "igm_index",
        "igm_date",
        "igm_year",
        "importer_name",
        "importer_address",
        "item_description",
        "quantity",
    ],
}

COLUMN_FRIENDLY_NAMES = {
    "AMNESTY": {
        "collectorate_name": "Collectorate",
        "name_of_owner": "Owner",
        "vehicle_details": "Vehicle Description",
        "chassis_number": "Chassis Number",
        "engine_capacity": "Engine Capacity",
        "ono_no": "Order In Original Number",
        "delivery_order_no": "Delivery Order Number",
        "delivery_order_date": "Delivery Order Date",
        "assessed_value": "Assessed Value",
        "total_amount_deposited": "Total Amount Deposited",
    },
    "84_TO_NOV22": {
        "cltcod": "GD Code",
        "betype": "GD Type",
        "mchnum": "GD Number",
        "mdat": "GD Date",
        "impnam": "Importer Name",
        "item_description": "Vehicle Description",
        "igm_no": "IGM Number",
        "igm_index": "Index Number",
        "igm_year": "IGM Year",
        "blno": "Bill of Lading Number",
        "bldate": "Bill of Lading Date",
    },
    "JUL22_TO_OCT23": {
        "cltcod": "GD Code",
        "betype": "GD Type",
        "mchnum": "GD Number",
        "gd_no_complete": "GD Number (with Code & Type)",
        "gd_date": "GD Date",
        "bl_no": "Bill of Lading Number",
        "bl_date": "Bill of Lading Date",
        "igm_no": "IGM Number",
        "igm_index": "Index Number",
        "igm_year": "IGM Year",
        "igm_date": "IGM Date",
        "importer_name": "Importer Name",
        "importer_address": "Importer Address",
        "item_description": "Vehicle Description",
        "quantity": "Quantity",
    },
}

RESULTS_DISPLAY_TEXT = {
    "chassis": {
        "AMNESTY": "Amnesty - Chassis No: {chassis_number}",
        "84_TO_NOV22": "84_TO_NOV22 - Item Desc: {item_description}",
        "JUL22_TO_OCT23": "JUL22_TO_OCT23 - Item Desc: {item_description}",
    },
    "gd_no_date": {
        "84_TO_NOV22": "84_TO_NOV22 - GD Code: {cltcod} | GD Type: {betype} | GD Number: {mchnum} | Item Desc: {item_description}",
        "JUL22_TO_OCT23": "JUL22_TO_OCT23 - GD Code: {cltcod} | GD Type: {betype} | GD Number: {mchnum} | Item Desc: {item_description}",
    },
    "igm_no_date": {
        "84_TO_NOV22": "84_TO_NOV22 - IGM No: {igm_no} | Index: {igm_index} | Item Desc: {item_description}",
        "JUL22_TO_OCT23": "JUL22_TO_OCT23 - IGM No: {igm_no} | Index: {igm_index} | Item Desc: {item_description}",
    },
    "bl_no": {
        "84_TO_NOV22": "84_TO_NOV22 - BL No: {blno} | Item Desc: {item_description}",
        "JUL22_TO_OCT23": "JUL22_TO_OCT23 - BL No: {bl_no} | Item Desc: {item_description}",
    },
    "ono_no": {
        "AMNESTY": "Amnesty - ONO No: {ono_no} | Chassis No: {chassis_number} | Vehicle Details: {vehicle_details}",
    },
    "delivery_order_no": {
        "AMNESTY": "Amnesty - D.O. No: {delivery_order_no} | Chassis No: {chassis_number} | Vehicle Details: {vehicle_details}",
    },
}

SEARCH_MAPPINGS = {
    "chassis": {
        "AMNESTY": ["chassis_number"],
        "84_TO_NOV22": ["item_description"],
        "JUL22_TO_OCT23": ["item_description"],
    },
    "gd_no_date": {
        "84_TO_NOV22": ["cltcod", "betype", "mchnum"],
        "JUL22_TO_OCT23": ["cltcod", "betype", "mchnum"],
    },
    "igm_no_date": {
        "84_TO_NOV22": ["igm_no", "igm_index", "igm_year"],
        "JUL22_TO_OCT23": ["igm_no", "igm_index", "igm_year"],
    },
    "bl_no": {
        "84_TO_NOV22": ["blno"],
        "JUL22_TO_OCT23": ["bl_no"],
    },
    "ono_no": {
        "AMNESTY": ["ono_no"],
    },
    "delivery_order_no": {
        "AMNESTY": ["delivery_order_no"],
    },
}

IDENTIFIER_FIELDS = {
    "chassis_number",
    "cltcod",
    "betype",
    "mchnum",
    "blno",
    "igm_no",
    "igm_index",
    "igm_year",
    "bl_no",
    "ono_no",
    "delivery_order_no",
}


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def read_packaged_update_config() -> dict:
    if not PACKAGED_UPDATE_CONFIG_PATH.exists():
        return {}

    try:
        payload = json.loads(PACKAGED_UPDATE_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


PACKAGED_UPDATE_CONFIG = read_packaged_update_config()
APP_VERSION = str(PACKAGED_UPDATE_CONFIG.get("app_version") or os.environ.get("PRAAL_APP_VERSION", "0.1.0")).strip()


def get_runtime_root() -> Path:
    android_private = os.environ.get("ANDROID_PRIVATE")
    if android_private:
        runtime_root = Path(android_private)
    else:
        runtime_root = APP_DIR / ".runtime"

    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root


def get_runtime_data_root() -> Path:
    root = get_runtime_root() / RUNTIME_DATA_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_runtime_updates_root() -> Path:
    root = get_runtime_root() / RUNTIME_UPDATES_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_runtime_overrides_root() -> Path:
    root = get_runtime_root() / RUNTIME_OVERRIDE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_runtime_static_override_root() -> Path:
    return get_runtime_overrides_root() / "static"


def get_runtime_database_path() -> Path:
    return get_runtime_data_root() / PACKAGED_DB_PATH.name


def get_staged_database_path() -> Path:
    return get_runtime_updates_root() / "offlinedata.next.db"


def get_update_state_path() -> Path:
    return get_runtime_root() / UPDATE_STATE_NAME


def get_runtime_update_config_path() -> Path:
    return get_runtime_root() / UPDATE_CONFIG_NAME


def append_startup_note(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    line = f"{timestamp} [{level}] {message}"
    STARTUP_NOTES.append(line)

    log_method = getattr(logging, level.lower(), logging.info)
    log_method(message)

    try:
        log_path = get_runtime_root() / RUNTIME_LOG_NAME
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")
    except Exception:
        pass


def normalize_term(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def display_value(value) -> str:
    if value is None:
        return "Not Available"
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return "Not Available"
    return text


def normalize_version(value: str) -> str:
    text = str(value or "").strip()
    if text[:1].lower() == "v":
        return text[1:]
    return text


def version_key(value: str):
    tokens = VERSION_TOKEN_PATTERN.findall(normalize_version(value))
    if not tokens:
        return ((0, 0),)

    keyed = []
    for token in tokens:
        if token.isdigit():
            keyed.append((0, int(token)))
        else:
            keyed.append((1, token.lower()))
    return tuple(keyed)


def is_version_newer(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)


def is_app_version_compatible(min_version: str) -> bool:
    min_version = str(min_version or "").strip()
    if not min_version:
        return True
    return version_key(APP_VERSION) >= version_key(min_version)


def default_update_config() -> dict[str, object]:
    return {
        "app_version": APP_VERSION,
        "bundled_database_version": str(PACKAGED_UPDATE_CONFIG.get("bundled_database_version") or "").strip(),
        "manifest_url": str(PACKAGED_UPDATE_CONFIG.get("manifest_url") or "").strip(),
        "check_interval_hours": int(PACKAGED_UPDATE_CONFIG.get("check_interval_hours", 12) or 12),
        "manifest_timeout_seconds": int(PACKAGED_UPDATE_CONFIG.get("manifest_timeout_seconds", 5) or 5),
        "download_timeout_seconds": int(PACKAGED_UPDATE_CONFIG.get("download_timeout_seconds", 900) or 900),
        "enable_database_updates": bool(PACKAGED_UPDATE_CONFIG.get("enable_database_updates", True)),
        "enable_file_updates": bool(PACKAGED_UPDATE_CONFIG.get("enable_file_updates", True)),
        "enable_apk_update_notice": bool(PACKAGED_UPDATE_CONFIG.get("enable_apk_update_notice", True)),
        "allowed_file_prefixes": list(PACKAGED_UPDATE_CONFIG.get("allowed_file_prefixes") or ["static/"]),
    }


def load_json_file(path: Path, fallback):
    if not path.exists():
        return fallback

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback

    return payload


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def load_update_config() -> dict[str, object]:
    config = default_update_config()

    packaged_payload = load_json_file(PACKAGED_UPDATE_CONFIG_PATH, {})
    if isinstance(packaged_payload, dict):
        config.update(packaged_payload)

    runtime_payload = load_json_file(get_runtime_update_config_path(), {})
    if isinstance(runtime_payload, dict):
        config.update(runtime_payload)

    manifest_override = os.environ.get("PRAAL_UPDATE_MANIFEST_URL", "").strip()
    if manifest_override:
        config["manifest_url"] = manifest_override

    prefixes = config.get("allowed_file_prefixes")
    if isinstance(prefixes, list):
        config["allowed_file_prefixes"] = [str(item).replace("\\", "/").strip() for item in prefixes if str(item).strip()]
    else:
        config["allowed_file_prefixes"] = ["static/"]

    for key, fallback in {
        "check_interval_hours": 12,
        "manifest_timeout_seconds": 5,
        "download_timeout_seconds": 900,
    }.items():
        try:
            config[key] = max(1, int(config.get(key, fallback)))
        except Exception:
            config[key] = fallback

    for key in ("enable_database_updates", "enable_file_updates", "enable_apk_update_notice"):
        config[key] = bool(config.get(key, True))

    config["app_version"] = str(config.get("app_version") or APP_VERSION).strip()
    config["bundled_database_version"] = str(config.get("bundled_database_version") or "").strip()
    config["manifest_url"] = str(config.get("manifest_url") or "").strip()
    return config


def default_update_state() -> dict[str, object]:
    return {
        "database": {
            "version": None,
            "staged_version": None,
            "seeded_at": None,
            "last_staged_at": None,
            "last_applied_at": None,
        },
        "files": {},
        "apk_notice": {
            "version": None,
            "url": None,
            "notes": None,
            "released_at": None,
        },
        "last_checked_at": None,
        "last_manifest_url": None,
        "last_error": None,
    }


def load_update_state() -> dict[str, object]:
    state = default_update_state()
    payload = load_json_file(get_update_state_path(), {})
    if not isinstance(payload, dict):
        return state

    database_state = payload.get("database")
    if isinstance(database_state, dict):
        state["database"].update(database_state)

    files_state = payload.get("files")
    if isinstance(files_state, dict):
        state["files"] = files_state

    apk_notice = payload.get("apk_notice")
    if isinstance(apk_notice, dict):
        state["apk_notice"].update(apk_notice)

    for key in ("last_checked_at", "last_manifest_url", "last_error"):
        state[key] = payload.get(key)

    return state


def save_update_state(state: dict[str, object]) -> None:
    atomic_write_json(get_update_state_path(), state)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def should_check_for_updates(config: dict[str, object], state: dict[str, object]) -> bool:
    manifest_url = str(config.get("manifest_url") or "").strip()
    if not manifest_url:
        return False

    last_checked_at = parse_timestamp(str(state.get("last_checked_at") or ""))
    if last_checked_at is None:
        return True

    interval_hours = int(config.get("check_interval_hours", 12))
    elapsed = datetime.now() - last_checked_at
    return elapsed.total_seconds() >= interval_hours * 3600


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_relative_update_path(value: str) -> str | None:
    normalized = str(value or "").replace("\\", "/").strip().lstrip("/")
    if not normalized:
        return None

    path = Path(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None

    return "/".join(path.parts)


def is_allowed_update_path(path: str, allowed_prefixes: list[str]) -> str | None:
    normalized = sanitize_relative_update_path(path)
    if not normalized:
        return None

    for prefix in allowed_prefixes:
        prefix_normalized = sanitize_relative_update_path(prefix)
        if not prefix_normalized:
            continue
        if normalized == prefix_normalized or normalized.startswith(prefix_normalized + "/"):
            return normalized
    return None


def open_url(url: str, timeout_seconds: int):
    request_obj = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"PRAAL-Mobile/{APP_VERSION}",
            "Accept": "application/json,application/octet-stream,*/*",
        },
    )
    return urllib.request.urlopen(request_obj, timeout=timeout_seconds)


def fetch_remote_json(url: str, timeout_seconds: int) -> dict:
    with open_url(url, timeout_seconds) as response:
        payload = response.read()

    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Update manifest must be a JSON object.")
    return data


def download_url_to_path(url: str, destination: Path, timeout_seconds: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".download")

    try:
        with open_url(url, timeout_seconds) as response, temp_path.open("wb") as handle:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                handle.write(chunk)
        temp_path.replace(destination)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def apply_staged_database(state: dict[str, object], config: dict[str, object]) -> tuple[Path, bool]:
    runtime_database_path = get_runtime_database_path()
    staged_database_path = get_staged_database_path()
    database_state = state["database"]
    changed = False

    if staged_database_path.exists() and database_state.get("staged_version"):
        runtime_database_path.parent.mkdir(parents=True, exist_ok=True)
        if runtime_database_path.exists():
            runtime_database_path.unlink()
        staged_database_path.replace(runtime_database_path)
        database_state["version"] = database_state.get("staged_version")
        database_state["staged_version"] = None
        database_state["last_applied_at"] = datetime.now().isoformat(timespec="seconds")
        changed = True
        append_startup_note(f"Applied staged database update: {runtime_database_path}")

    if not runtime_database_path.exists() and PACKAGED_DB_PATH.exists():
        runtime_database_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACKAGED_DB_PATH, runtime_database_path)
        if not database_state.get("version"):
            database_state["version"] = str(config.get("bundled_database_version") or "").strip() or None
        database_state["seeded_at"] = datetime.now().isoformat(timespec="seconds")
        changed = True
        append_startup_note(f"Seeded runtime database from packaged copy: {runtime_database_path}")
    elif runtime_database_path.exists() and not database_state.get("version"):
        bundled_version = str(config.get("bundled_database_version") or "").strip()
        if bundled_version:
            database_state["version"] = bundled_version
            changed = True

    return runtime_database_path, changed


def detect_template_roots() -> list[Path]:
    roots: list[Path] = []
    standard = APP_DIR / "templates"
    if (standard / "index.html").exists():
        roots.append(standard)

    if (APP_DIR / "index.html").exists():
        roots.append(APP_DIR)

    return roots


def detect_static_roots() -> list[Path]:
    roots: list[Path] = []
    roots.append(get_runtime_static_override_root())

    standard = APP_DIR / "static"
    if standard.exists():
        roots.append(standard)

    root_assets = ["style.css", "script.js", "offline_bootstrap.css", "offline_ui.js"]
    if any((APP_DIR / name).exists() for name in root_assets):
        roots.append(APP_DIR)

    return roots


def select_database_path() -> Path:
    config = load_update_config()
    state = load_update_state()
    runtime_database_path, changed = apply_staged_database(state, config)

    candidates = [runtime_database_path, PACKAGED_DB_PATH, APP_DIR / "offlinedata.db"]
    for path in candidates:
        if path.exists():
            append_startup_note(f"Database candidate found: {path} ({path.stat().st_size} bytes)")
            if changed:
                save_update_state(state)
            return path

    raise FileNotFoundError(
        "The packaged SQLite database is missing. Ensure offlinedata.db is inside mobile_app/database before build."
    )


def startup_summary(database_path: Path, template_roots: list[Path], static_roots: list[Path]) -> dict:
    summary: dict[str, object] = {
        "app_dir": str(APP_DIR),
        "app_version": APP_VERSION,
        "database_path": str(database_path),
        "database_exists": database_path.exists(),
        "database_size": database_path.stat().st_size if database_path.exists() else None,
        "template_roots": [str(path) for path in template_roots],
        "static_roots": [str(path) for path in static_roots],
        "runtime_root": str(get_runtime_root()),
        "app_dir_entries": sorted(path.name for path in APP_DIR.iterdir()) if APP_DIR.exists() else [],
    }

    try:
        usage = os.statvfs(str(get_runtime_root()))
        free_bytes = usage.f_bavail * usage.f_frsize
        summary["runtime_free_bytes"] = free_bytes
    except Exception:
        summary["runtime_free_bytes"] = None

    return summary


def update_apk_notice_from_manifest(manifest: dict, state: dict[str, object], enabled: bool) -> None:
    notice = state["apk_notice"]
    app_payload = manifest.get("app")
    if not enabled or not isinstance(app_payload, dict):
        notice.update({"version": None, "url": None, "notes": None, "released_at": None})
        return

    version = str(app_payload.get("version") or "").strip()
    url = str(app_payload.get("url") or "").strip()
    notes = str(app_payload.get("notes") or "").strip() or None
    released_at = str(app_payload.get("released_at") or "").strip() or None

    if version and url and is_version_newer(version, APP_VERSION):
        notice.update({
            "version": version,
            "url": url,
            "notes": notes,
            "released_at": released_at,
        })
    else:
        notice.update({"version": None, "url": None, "notes": None, "released_at": None})


def stage_database_update(manifest: dict, state: dict[str, object], config: dict[str, object]) -> None:
    database_payload = manifest.get("database")
    if not isinstance(database_payload, dict):
        return

    remote_version = str(database_payload.get("version") or "").strip()
    remote_url = str(database_payload.get("url") or "").strip()
    expected_hash = str(database_payload.get("sha256") or "").strip().lower()
    min_app_version = str(database_payload.get("min_app_version") or manifest.get("minimum_app_version") or "").strip()

    if not remote_version or not remote_url:
        return

    if not is_app_version_compatible(min_app_version):
        append_startup_note(
            f"Skipped database update {remote_version}; app version {APP_VERSION} is below required {min_app_version}.",
            level="INFO",
        )
        return

    database_state = state["database"]
    local_version = str(
        database_state.get("staged_version")
        or database_state.get("version")
        or config.get("bundled_database_version")
        or ""
    ).strip()

    if local_version and not is_version_newer(remote_version, local_version):
        return

    staged_database_path = get_staged_database_path()
    staged_database_path.parent.mkdir(parents=True, exist_ok=True)
    download_url_to_path(remote_url, staged_database_path, int(config.get("download_timeout_seconds", 900)))

    if expected_hash:
        actual_hash = calculate_sha256(staged_database_path)
        if actual_hash.lower() != expected_hash:
            staged_database_path.unlink(missing_ok=True)
            raise ValueError("Downloaded database hash does not match the manifest sha256.")

    database_state["staged_version"] = remote_version
    database_state["last_staged_at"] = datetime.now().isoformat(timespec="seconds")
    append_startup_note(f"Staged new database version {remote_version} for next app launch.")


def process_file_updates(manifest: dict, state: dict[str, object], config: dict[str, object]) -> None:
    files_payload = manifest.get("files")
    if not isinstance(files_payload, list):
        return

    allowed_prefixes = list(config.get("allowed_file_prefixes") or ["static/"])
    runtime_overrides = get_runtime_overrides_root()
    runtime_overrides.mkdir(parents=True, exist_ok=True)

    for entry in files_payload:
        if not isinstance(entry, dict):
            continue

        relative_path = is_allowed_update_path(str(entry.get("path") or ""), allowed_prefixes)
        if not relative_path:
            continue

        version = str(entry.get("version") or "").strip()
        url = str(entry.get("url") or "").strip()
        expected_hash = str(entry.get("sha256") or "").strip().lower()
        min_app_version = str(entry.get("min_app_version") or manifest.get("minimum_app_version") or "").strip()

        if not version or not url or not is_app_version_compatible(min_app_version):
            continue

        local_file_state = state["files"].get(relative_path, {})
        local_version = str(local_file_state.get("version") or "").strip()
        if local_version and not is_version_newer(version, local_version):
            continue

        target_path = runtime_overrides / Path(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        download_url_to_path(url, target_path, int(config.get("download_timeout_seconds", 900)))

        if expected_hash:
            actual_hash = calculate_sha256(target_path)
            if actual_hash.lower() != expected_hash:
                target_path.unlink(missing_ok=True)
                raise ValueError(f"Downloaded file hash mismatch for {relative_path}.")

        state["files"][relative_path] = {
            "version": version,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        append_startup_note(f"Updated runtime file override: {relative_path} ({version})")


def run_update_cycle() -> None:
    global UPDATE_THREAD_STARTED

    config = load_update_config()
    state = load_update_state()
    manifest_url = str(config.get("manifest_url") or "").strip()

    try:
        if not manifest_url:
            append_startup_note("Update check skipped because manifest_url is not configured.")
            return

        append_startup_note(f"Checking remote manifest: {manifest_url}")
        manifest = fetch_remote_json(manifest_url, int(config.get("manifest_timeout_seconds", 5)))
        update_apk_notice_from_manifest(manifest, state, bool(config.get("enable_apk_update_notice", True)))

        if bool(config.get("enable_database_updates", True)):
            stage_database_update(manifest, state, config)

        if bool(config.get("enable_file_updates", True)):
            process_file_updates(manifest, state, config)

        state["last_error"] = None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as error:
        state["last_error"] = f"{type(error).__name__}: {error}"
        append_startup_note(f"Remote update check failed: {error}", level="ERROR")
    except Exception as error:
        state["last_error"] = f"{type(error).__name__}: {error}"
        append_startup_note(f"Unexpected update failure: {error}", level="ERROR")
    finally:
        state["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
        state["last_manifest_url"] = manifest_url
        save_update_state(state)
        with UPDATE_THREAD_LOCK:
            UPDATE_THREAD_STARTED = False


def start_background_update_check() -> None:
    global UPDATE_THREAD_STARTED

    config = load_update_config()
    state = load_update_state()
    manifest_url = str(config.get("manifest_url") or "").strip()

    if not manifest_url:
        append_startup_note("Remote updater is disabled until manifest_url is configured.")
        return

    if not should_check_for_updates(config, state):
        append_startup_note("Remote update check skipped because the last check is still fresh.")
        return

    with UPDATE_THREAD_LOCK:
        if UPDATE_THREAD_STARTED:
            return
        UPDATE_THREAD_STARTED = True

    worker = threading.Thread(target=run_update_cycle, name="praal-update-worker", daemon=True)
    worker.start()
    append_startup_note("Remote update worker started.")


def create_flask_app(database_path: Path) -> Flask:
    template_roots = detect_template_roots()
    static_roots = detect_static_roots()

    if not template_roots:
        raise FileNotFoundError("No usable template directory found (templates/index.html missing).")

    flask_app = Flask(__name__, template_folder=str(template_roots[0]), static_folder=None)
    if len(template_roots) > 1:
        flask_app.jinja_loader = ChoiceLoader([FileSystemLoader(str(path)) for path in template_roots])

    flask_app.config["DATABASE_PATH"] = str(database_path)
    flask_app.config["STATIC_ROOTS"] = static_roots
    flask_app.config["STARTUP_SUMMARY"] = startup_summary(database_path, template_roots, static_roots)
    flask_app.secret_key = "praal-offline-mobile"

    append_startup_note(f"Using template roots: {[str(path) for path in template_roots]}")
    append_startup_note(f"Using static roots: {[str(path) for path in static_roots]}")

    @flask_app.context_processor
    def inject_update_context() -> dict[str, object]:
        state = load_update_state()
        apk_notice = state.get("apk_notice", {})
        database_state = state.get("database", {})
        available_version = str(apk_notice.get("version") or "").strip()
        download_url = str(apk_notice.get("url") or "").strip()

        return {
            "app_version": APP_VERSION,
            "apk_update_notice": {
                "available": bool(available_version and download_url and is_version_newer(available_version, APP_VERSION)),
                "version": available_version,
                "url": download_url,
                "notes": apk_notice.get("notes"),
                "released_at": apk_notice.get("released_at"),
            },
            "database_update_status": {
                "current_version": database_state.get("version"),
                "staged": bool(database_state.get("staged_version")),
                "staged_version": database_state.get("staged_version"),
            },
        }

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            db_path = Path(flask_app.config["DATABASE_PATH"])
            db_uri = f"file:{db_path.as_posix()}?mode=ro"

            try:
                connection = sqlite3.connect(db_uri, uri=True, check_same_thread=False)
                append_startup_note(f"SQLite opened in read-only mode: {db_path}")
            except sqlite3.Error as error:
                append_startup_note(
                    f"Read-only SQLite open failed ({error}); falling back to direct open.",
                    level="ERROR",
                )
                connection = sqlite3.connect(str(db_path), check_same_thread=False)

            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA query_only = ON")
            except sqlite3.Error:
                pass

            g.db = connection

        return g.db

    @flask_app.teardown_appcontext
    def close_db(_exception) -> None:
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @flask_app.route("/static/<path:filename>", endpoint="static")
    def serve_static(filename: str):
        roots: list[Path] = flask_app.config.get("STATIC_ROOTS", [])
        candidates = [filename, filename.lstrip("/"), Path(filename).name]

        for root in roots:
            for relative in candidates:
                candidate = root / relative
                if candidate.exists() and candidate.is_file():
                    return send_from_directory(str(root), relative)

        abort(404)

    @flask_app.route("/")
    def index():
        try:
            return render_template("index.html")
        except TemplateNotFound as error:
            append_startup_note(f"Template render failed on '/': {error}", level="ERROR")
            return (
                "<h3>PRAAL Offline - Startup Template Error</h3>"
                "<p>Open <code>/__health</code> for diagnostics.</p>",
                500,
            )

    @flask_app.route("/search", methods=["GET", "POST"])
    def search():
        source = request.form if request.method == "POST" else request.args
        search_type = source.get("search_type", "").strip()
        query_params = {
            key: value.strip()
            for key, value in source.items()
            if key != "search_type" and value and value.strip()
        }
        return redirect(url_for("show_results", search_type=search_type, **query_params))

    @flask_app.route("/results")
    def show_results():
        search_type = request.args.get("search_type", "").strip()
        results = perform_search(get_db(), search_type, request.args.to_dict(flat=True))
        return render_template(
            "results.html",
            results=results,
            search_type=search_type,
            now=datetime.now(),
        )

    @flask_app.route("/data/<int:record_id>")
    def show_data(record_id: int):
        row = get_db().execute(
            "SELECT * FROM records WHERE id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return redirect(url_for("index"))

        row_dict = dict(row)
        file_key = row_dict["source_file"]
        ordered_data = {}
        for logical_column in DISPLAY_ORDER.get(file_key, []):
            friendly_name = COLUMN_FRIENDLY_NAMES.get(file_key, {}).get(
                logical_column,
                logical_column.replace("_", " ").title(),
            )
            ordered_data[friendly_name] = display_value(row_dict.get(logical_column))

        return render_template(
            "data.html",
            data=ordered_data,
            file=file_key,
            now=datetime.now(),
        )

    @flask_app.route("/__health")
    def health():
        payload = {
            "status": "ok",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "summary": flask_app.config.get("STARTUP_SUMMARY", {}),
            "update_state": load_update_state(),
            "update_config": {
                key: value
                for key, value in load_update_config().items()
                if key != "download_timeout_seconds"
            },
            "notes": STARTUP_NOTES[-80:],
        }
        return jsonify(payload)

    @flask_app.route("/__update-status")
    def update_status():
        return jsonify(
            {
                "app_version": APP_VERSION,
                "config": load_update_config(),
                "state": load_update_state(),
            }
        )

    return flask_app


def perform_search(connection: sqlite3.Connection, search_type: str, params: dict[str, str]) -> list[dict]:
    active_terms = {
        key: value.strip()
        for key, value in params.items()
        if key != "search_type" and value and value.strip()
    }
    if not active_terms:
        return []

    if search_type == "combined":
        search_map: dict[str, list[str]] = {}
        for mapping in SEARCH_MAPPINGS.values():
            for file_key, columns in mapping.items():
                search_map.setdefault(file_key, [])
                for column in columns:
                    if column not in search_map[file_key]:
                        search_map[file_key].append(column)
    else:
        search_map = SEARCH_MAPPINGS.get(search_type, {})

    if not search_map:
        return []

    single_field_types = {"chassis", "bl_no", "ono_no", "delivery_order_no"}
    unified_term = None
    if search_type in single_field_types:
        for value in active_terms.values():
            unified_term = value
            break

    all_results: list[dict] = []
    for file_key, logical_columns in search_map.items():
        source_conditions = ["source_file = ?"]
        query_args: list[str] = [file_key]
        terms_applied = False

        relevant_terms = {
            logical_column: active_terms.get(logical_column)
            for logical_column in logical_columns
            if active_terms.get(logical_column)
        }

        if search_type != "combined" and search_type not in single_field_types and not relevant_terms:
            continue

        for logical_column in logical_columns:
            term = unified_term if search_type in single_field_types else active_terms.get(logical_column)
            if not term:
                continue

            terms_applied = True
            source_conditions.append(build_condition(logical_column))
            normalized_term = normalize_term(term)

            if logical_column in IDENTIFIER_FIELDS:
                query_args.extend([normalized_term, f"{normalized_term}%"])
            else:
                query_args.append(normalized_term)

        if not terms_applied:
            continue

        query = (
            "SELECT * FROM records WHERE "
            + " AND ".join(source_conditions)
            + " ORDER BY id LIMIT 500"
        )
        rows = connection.execute(query, query_args).fetchall()

        for row in rows:
            row_dict = dict(row)
            row_dict["display_text"] = render_display_text(search_type, row_dict)
            all_results.append(row_dict)

    return all_results


def normalized_sql(logical_column: str) -> str:
    return f"lower(trim(COALESCE({logical_column}, '')))"


def build_condition(logical_column: str) -> str:
    expression = normalized_sql(logical_column)
    if logical_column in IDENTIFIER_FIELDS:
        return f"({expression} = ? OR {expression} LIKE ?)"
    return f"instr({expression}, ?) > 0"


def render_display_text(search_type: str, row_dict: dict) -> str:
    template = RESULTS_DISPLAY_TEXT.get(search_type, {}).get(
        row_dict["source_file"],
        "{source_file} - Record #{id}",
    )
    safe_row = defaultdict(lambda: "Not Available")
    for key, value in row_dict.items():
        safe_row[key] = display_value(value)
    return template.format_map(safe_row)


def create_failure_app(error: Exception, trace_text: str) -> Flask:
    fallback = Flask(__name__)

    @fallback.route("/", defaults={"path": ""})
    @fallback.route("/<path:path>")
    def failed_startup(path: str):
        log_hint = get_runtime_root() / RUNTIME_LOG_NAME
        body = (
            "<h3>PRAAL Offline Startup Failed</h3>"
            "<p>The app failed before opening the main page.</p>"
            f"<p>Error: <code>{type(error).__name__}: {error}</code></p>"
            f"<p>Runtime log: <code>{log_hint}</code></p>"
            "<p>Open <code>/__health</code> for structured diagnostics.</p>"
            f"<pre>{trace_text}</pre>"
        )
        return body, 500

    @fallback.route("/__health")
    def failed_health():
        return jsonify(
            {
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
                "update_state": load_update_state(),
                "notes": STARTUP_NOTES[-80:],
                "traceback": trace_text,
            }
        ), 500

    return fallback


append_startup_note(f"App directory: {APP_DIR}")
append_startup_note(f"Android private path: {os.environ.get('ANDROID_PRIVATE', '(not set)')}")

try:
    DATABASE_PATH = select_database_path()
    app = create_flask_app(DATABASE_PATH)
    start_background_update_check()
    append_startup_note("Application initialized successfully.")
except Exception as startup_error:
    startup_traceback = traceback.format_exc()
    append_startup_note(f"Fatal startup error: {startup_error}", level="ERROR")
    app = create_failure_app(startup_error, startup_traceback)


if __name__ == "__main__":
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False, threaded=True)
