from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, url_for


APP_DIR = Path(__file__).resolve().parent
PACKAGED_DB_PATH = APP_DIR / "database" / "offlinedata.db"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("PRAAL_PORT", "5000"))

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


def normalize_term(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def display_value(value) -> str:
    if value is None:
        return "Not Available"
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return "Not Available"
    return text


def get_runtime_root() -> Path:
    android_private = os.environ.get("ANDROID_PRIVATE")
    if android_private:
        runtime_root = Path(android_private)
    else:
        runtime_root = APP_DIR / ".runtime"

    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root


def copy_runtime_database() -> Path:
    if not PACKAGED_DB_PATH.exists():
        raise FileNotFoundError(
            "The packaged SQLite database is missing. Run converter.py before rebuilding the APK."
        )

    runtime_dir = get_runtime_root() / "database"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_db_path = runtime_dir / "offlinedata.db"

    should_copy = not runtime_db_path.exists()
    if runtime_db_path.exists():
        should_copy = PACKAGED_DB_PATH.stat().st_mtime > runtime_db_path.stat().st_mtime

    if should_copy:
        shutil.copy2(PACKAGED_DB_PATH, runtime_db_path)

    return runtime_db_path


def create_flask_app(database_path: Path) -> Flask:
    flask_app = Flask(
        __name__,
        template_folder=str(APP_DIR / "templates"),
        static_folder=str(APP_DIR / "static"),
    )
    flask_app.config["DATABASE_PATH"] = str(database_path)
    flask_app.secret_key = "praal-offline-mobile"

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            connection = sqlite3.connect(flask_app.config["DATABASE_PATH"])
            connection.row_factory = sqlite3.Row
            g.db = connection
        return g.db

    @flask_app.teardown_appcontext
    def close_db(_exception) -> None:
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @flask_app.route("/")
    def index():
        return render_template("index.html")

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

    @flask_app.route("/guide")
    def guide():
        return render_template("guide.html")

    @flask_app.route("/faq")
    def faq():
        return render_template("faq.html")

    @flask_app.route("/about")
    def about():
        return render_template("about.html")

    @flask_app.route("/contact")
    def contact():
        return render_template("contact.html")

    @flask_app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

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


DATABASE_PATH = copy_runtime_database()
app = create_flask_app(DATABASE_PATH)


if __name__ == "__main__":
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False, threaded=True)



