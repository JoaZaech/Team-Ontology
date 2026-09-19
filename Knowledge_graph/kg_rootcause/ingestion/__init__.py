"""Validate source identifiers and monetary semantics before constructing knowledge."""
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from ..common import cents, timestamp

MONEY = {"amount", "billing_amount_chf", "items_subtotal", "delivery_fee", "unit_price"}
BOOL = {"online_enabled", "international_enabled", "virtual_card", "card_present", "recurring", "recurring_capable"}
INT = {"quantity", "line_no", "replay_order", "event_count", "recent_attempt_count_10m", "approved_merchant_transaction_count_before", "approved_device_transaction_count_before"}
DATES = {"opened_on", "first_used_on", "expires_on", "delivery_by", "rate_date"}
TIMES = {"timestamp", "valid_from", "valid_until", "last_approved_at"}
OPTIONAL = {"customer_device_id", "related_transaction_id", "last_approved_at", "spend_in_period_before_chf", "delivery_by", "related_authorization_id", "related_authorization_status"}


class DataQualityError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__(json.dumps(report, indent=2))


def load_dataset(directory):
    directory = Path(directory)
    contract = json.loads((directory / "schemas/data_pack.schema.json").read_text())
    contracts = dict(contract["x-csv-contracts"])
    history_schema = json.loads((directory / "schemas/authorization_history.schema.json").read_text())
    contracts["authorization_history.csv"] = {"key": "authorization_id", "header": history_schema["properties"]["columns"]["const"]}
    tables, indexes, errors = {}, {}, []
    def check(condition, message):
        if not condition:
            errors.append(message)
    for filename, spec in contracts.items():
        name = filename[:-4]
        try:
            with (directory / filename).open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != spec["header"]:
                    errors.append(f"{filename}: header differs from supplied contract")
                    continue
                rows = list(reader)
        except OSError as exc:
            errors.append(f"{filename}: {exc}")
            continue
        tables[name], indexes[name] = [], {}
        key_fields = spec["key"] if isinstance(spec["key"], list) else [spec["key"]]
        for number, row in enumerate(rows, 2):
            source_id = "|".join(str(row.get(k, "")) for k in key_fields)
            check(source_id not in indexes[name], f"{filename}:{number}: duplicate key {source_id}")
            converted = {}
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("Malformed CSV row")
                for field, value in row.items():
                    if value == "":
                        if field not in OPTIONAL:
                            raise ValueError(f"Missing {field}")
                        converted[field] = None
                    elif field in MONEY or field.endswith("_chf"):
                        if Decimal(value).as_tuple().exponent < -2 or not Decimal(value).is_finite():
                            raise ValueError(f"Invalid money {field}")
                        converted[field] = cents(value)
                    elif field == "rate":
                        rate = Decimal(value)
                        if not rate.is_finite() or rate <= 0:
                            raise ValueError("Invalid FX rate")
                        converted[field] = value
                    elif field in BOOL:
                        if value not in ("true", "false"):
                            raise ValueError(f"Invalid boolean {field}")
                        converted[field] = value == "true"
                    elif field in INT:
                        converted[field] = int(value)
                        if converted[field] < (1 if field in {"quantity", "line_no", "replay_order", "event_count"} else 0):
                            raise ValueError(f"Invalid integer {field}")
                    else:
                        if field in TIMES:
                            timestamp(value)
                        if field in DATES:
                            date.fromisoformat(value)
                        converted[field] = value
                if name == "authorization_history":
                    for field, rule in history_schema["x-csv-column-contract"].items():
                        value = converted[field]
                        if value is None:
                            check(rule["nullable"], f"{source_id}: null {field}")
                        elif "enum" in rule:
                            check(value in rule["enum"], f"{source_id}: invalid {field}")
                        elif "pattern" in rule:
                            check(re.fullmatch(rule["pattern"], value), f"{source_id}: invalid {field}")
                converted["_source"] = {"source_file": filename, "source_id": source_id, "source_fields": spec["header"], "event_time": converted.get("timestamp"), "source_as_of": "2026-08-01T00:00:00Z", "graph_version": "kg-v1"}
                tables[name].append(converted)
                indexes[name][source_id] = converted
            except (ValueError, ArithmeticError) as exc:
                errors.append(f"{filename}:{number}: {exc}")
    if errors:
        raise DataQualityError({"valid": False, "errors": errors})
    def join(row, field, table, optional=False):
        value = row.get(field)
        if value is None and optional:
            return None
        found = indexes[table].get(value)
        check(found is not None, f"{row['_source']['source_id']}: invalid {field} {value}")
        return found
    for filename, spec in contracts.items():
        for row in tables[filename[:-4]]:
            for fk in spec.get("foreign_keys", []):
                field, target = fk.split(" -> ")
                join(row, field, target.split(".")[0])
    for row in tables["scenario_authorities"]:
        card = join(row, "card_id", "cards")
        if card and card["account_id"] in indexes["accounts"]:
            check(indexes["accounts"][card["account_id"]]["customer_id"] == row["customer_id"], "Authority ownership mismatch")
        check(timestamp(row["valid_from"]) < timestamp(row["valid_until"]), "Authority interval invalid")
    for table, prefix, related in [("authorization_history", "TR", "related_transaction_id"), ("purchase_attempts", "AU", "related_authorization_id")]:
        for row in tables[table]:
            check(row["authorization_id"].startswith(prefix), "Event namespace mismatch")
            card = join(row, "card_id", "cards")
            merchant = join(row, "merchant_id", "merchants")
            parent = join(row, related, table, optional=True)
            if parent:
                check(parent["card_id"] == row["card_id"] and timestamp(parent["timestamp"]) < timestamp(row["timestamp"]), "Related authorization is not earlier on same card")
            if table == "authorization_history":
                account = join(row, "account_id", "accounts")
                join(row, "customer_id", "customers")
                if card and account:
                    check(card["account_id"] == row["account_id"] and account["customer_id"] == row["customer_id"], "Historical ownership mismatch")
                if merchant:
                    for field in ("merchant_category", "merchant_country", "merchant_name", "merchant_mcc"):
                        check(row[field] == merchant[field], f"{row['authorization_id']}: {field} mismatch")
                check((row["amount"] < 0) == (row["transaction_type"] == "refund"), "Refund sign mismatch")
            else:
                join(row, "scenario_id", "scenario_catalogue")
                authority = join(row, "authority_id", "scenario_authorities")
                if authority:
                    check(authority["card_id"] == row["card_id"], "Attempt authority card mismatch")
                for field in ("order_returnable", "order_cancellable"):
                    check(row[field] in ("true", "false", "unknown", "not_applicable"), f"Invalid term {field}")
                check(row["amount"] >= 0 and row["delivery_fee"] >= 0, "Negative purchase amount")
                check(row["amount"] == row["items_subtotal"] + row["delivery_fee"], "Order total mismatch")
            fx = indexes["fx_rates"].get(row["currency"])
            check(fx is not None, "Missing FX rate")
            if fx:
                check(cents(Decimal(row["amount"]) / 100 * Decimal(fx["rate"])) == row["billing_amount_chf"], "FX billing mismatch")
    currencies = set(contract["x-enums"]["currencies"])
    for rows in tables.values():
        for row in rows:
            for field in ("currency", "base_currency", "from_currency", "to_currency"):
                if field in row:
                    check(row[field] in currencies, f"Invalid currency in {field}")
    for fx in tables["fx_rates"]:
        check(fx["rate_date"] == contract["x-currency-contract"]["rate_date"] and fx["source"] == contract["x-currency-contract"]["source"], "FX contract date/source mismatch")
        check(fx["to_currency"] == "CHF" and Decimal(fx["rate"]) > 0, "Invalid FX rate")
    baskets = defaultdict(list)
    for row in tables["purchase_attempt_items"]:
        item = indexes["items"].get(row["item_id"])
        if item:
            check(all(row[k] == item[k] for k in ("item_name", "item_category")), "Item catalogue mismatch")
        attempt = indexes["purchase_attempts"].get(row["authorization_id"])
        if attempt:
            check(row["currency"] == attempt["currency"], "Basket currency mismatch")
        baskets[row["authorization_id"]].append(row)
    for row in tables["purchase_attempts"]:
        lines = baskets[row["authorization_id"]]
        check(bool(lines), "Missing basket")
        check(sum(x["quantity"] * x["unit_price"] for x in lines) == row["items_subtotal"], f"{row['authorization_id']}: basket total mismatch")
    for scenario in tables["scenario_catalogue"]:
        rows = sorted((r for r in tables["purchase_attempts"] if r["scenario_id"] == scenario["scenario_id"]), key=lambda r: r["replay_order"])
        check([r["replay_order"] for r in rows] == list(range(1, scenario["event_count"] + 1)), "Scenario order/count mismatch")
        check(len({r["authority_id"] for r in rows}) == 1, "Scenario authority mismatch")
        check(all(timestamp(a["timestamp"]) <= timestamp(b["timestamp"]) for a, b in zip(rows, rows[1:])), "Scenario timestamps out of order")
    report = {"valid": not errors, "errors": errors, "row_counts": {k: len(v) for k, v in tables.items()}, "money_unit": "integer minor units; *_chf fields are CHF cents", "warnings": ["FX rates are synthetic fixed constants dated 2026-08-01; historical billing uses supplied billing amounts, never future FX lookup.", "Static catalogue has no historical change log; time correctness is guaranteed for event evidence, not reconstructed catalogue versions."]}
    if errors:
        raise DataQualityError(report)
    return {"tables": tables, "indexes": indexes}, report
