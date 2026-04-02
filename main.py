from __future__ import annotations

import logging
import os
import sqlite3
import traceback
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


def get_runtime_root() -> Path:
    android_private = os.environ.get("ANDROID_PRIVATE")
    if android_private:
        runtime_root = Path(android_private)
    else:
        runtime_root = APP_DIR / ".runtime"

    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root


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


def detect_template_roots() -> list[Path]:
    roots: list[Path] = []
    standard = APP_DIR / "templates"
    if (standard / "index.html").exists():
        roots.append(standard)

    # Fallback for flattened packaging where templates are at app root.
    if (APP_DIR / "index.html").exists():
        roots.append(APP_DIR)

    return roots


def detect_static_roots() -> list[Path]:
    roots: list[Path] = []
    standard = APP_DIR / "static"
    if standard.exists():
        roots.append(standard)

    # Fallback for flattened packaging where css/js files are at app root.
    root_assets = ["style.css", "script.js", "offline_bootstrap.css", "offline_ui.js"]
    if any((APP_DIR / name).exists() for name in root_assets):
        roots.append(APP_DIR)

    return roots


def select_database_path() -> Path:
    candidates = [PACKAGED_DB_PATH, APP_DIR / "offlinedata.db"]

    for path in candidates:
        if path.exists():
            append_startup_note(f"Database candidate found: {path} ({path.stat().st_size} bytes)")
            return path

    raise FileNotFoundError(
        "The packaged SQLite database is missing. Ensure offlinedata.db is inside mobile_app/database before build."
    )


def startup_summary(database_path: Path, template_roots: list[Path], static_roots: list[Path]) -> dict:
    summary: dict[str, object] = {
        "app_dir": str(APP_DIR),
        "database_path": str(database_path),
        "database_exists": database_path.exists(),
        "database_size": database_path.stat().st_size if database_path.exists() else None,
        "template_roots": [str(path) for path in template_roots],
        "static_roots": [str(path) for path in static_roots],
        "app_dir_entries": sorted(path.name for path in APP_DIR.iterdir()) if APP_DIR.exists() else [],
    }

    try:
        usage = os.statvfs(str(get_runtime_root()))
        free_bytes = usage.f_bavail * usage.f_frsize
        summary["runtime_free_bytes"] = free_bytes
    except Exception:
        summary["runtime_free_bytes"] = None

    return summary


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
            "notes": STARTUP_NOTES[-80:],
        }
        return jsonify(payload)

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
    append_startup_note("Application initialized successfully.")
except Exception as startup_error:
    startup_traceback = traceback.format_exc()
    append_startup_note(f"Fatal startup error: {startup_error}", level="ERROR")
    app = create_failure_app(startup_error, startup_traceback)


if __name__ == "__main__":
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False, threaded=True)

