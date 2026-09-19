"""Build a small, deterministic online knowledge-graph projection.

The source CSVs remain the system of record.  This module creates a rebuildable
JSON projection containing only facts needed by the authorization path:
card/merchant, card/device and card/category summaries, recent activity and
card amount distributions.  It deliberately does not make an approval
decision; ``lookup_context`` returns evidence for the existing guardrail.

Examples:
    python precompute.py --data-dir ../../viseca-2026/data --output build
    python precompute.py --data-dir ../../viseca-2026/data --lookup CA0001 ME0001 DVC-13A598
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _cents(value: str) -> int:
    # The data contract has two decimal places.  Avoid binary floating point
    # for all persisted monetary aggregates.
    whole, _, fraction = value.strip().partition(".")
    fraction = (fraction + "00")[:2]
    sign = -1 if whole.startswith("-") else 1
    whole = whole.lstrip("-")
    return sign * (int(whole or "0") * 100 + int(fraction))


def _chf(cents: int) -> float:
    return round(cents / 100, 2)


def _percentile(values: list[int], value: int) -> float:
    if not values:
        return 0.5
    ordered = sorted(values)
    less_or_equal = sum(item <= value for item in ordered)
    return round(less_or_equal / len(ordered), 4)


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _summary(values: list[int], approved: int, declined: int, last: str | None) -> dict[str, Any]:
    return {
        "approved_count": approved,
        "declined_count": declined,
        "approved_amount_chf": _chf(sum(values)),
        "average_approved_amount_chf": _chf(round(sum(values) / len(values))) if values else None,
        "approved_amount_p95_chf": _chf(_p95(values)) if values else None,
        "last_approved_at": last,
    }


def build_projection(data_dir: str | Path) -> dict[str, Any]:
    root = Path(data_dir)
    with (root / "authorization_history.csv").open(newline="", encoding="utf-8") as stream:
        history = list(csv.DictReader(stream))
    with (root / "merchants.csv").open(newline="", encoding="utf-8") as stream:
        merchants = {row["merchant_id"]: row for row in csv.DictReader(stream)}
    with (root / "customers.csv").open(newline="", encoding="utf-8") as stream:
        customers = {row["customer_id"]: row for row in csv.DictReader(stream)}
    with (root / "accounts.csv").open(newline="", encoding="utf-8") as stream:
        accounts = {row["account_id"]: row for row in csv.DictReader(stream)}
    with (root / "cards.csv").open(newline="", encoding="utf-8") as stream:
        cards = {row["card_id"]: row for row in csv.DictReader(stream)}

    # Only approved purchase history contributes to familiarity or normal
    # amount distributions. Declines remain evidence but not completed spend.
    card_merchant: dict[tuple[str, str], dict[str, Any]] = {}
    card_device: dict[tuple[str, str], dict[str, Any]] = {}
    card_category: dict[tuple[str, str], dict[str, Any]] = {}
    card_amounts: dict[str, list[int]] = defaultdict(list)
    card_recent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    device_cards: dict[str, set[str]] = defaultdict(set)

    ordered = sorted(history, key=lambda row: (_timestamp(row["timestamp"]), row["authorization_id"]))
    for row in ordered:
        card_id = row["card_id"]
        merchant_id = row["merchant_id"]
        category = row["merchant_category"]
        device_id = row["customer_device_id"].strip()
        approved = row["status"] == "approved" and row["transaction_type"] == "purchase"
        amount = _cents(row["billing_amount_chf"])
        if device_id:
            device_cards[device_id].add(card_id)

        if approved:
            card_amounts[card_id].append(amount)
            for key, bucket in (
                ((card_id, merchant_id), card_merchant),
                ((card_id, category), card_category),
            ):
                item = bucket.setdefault(key, {"values": [], "approved_count": 0, "declined_count": 0, "last_approved_at": None})
                item["values"].append(amount)
                item["approved_count"] += 1
                item["last_approved_at"] = row["timestamp"]
            if device_id:
                item = card_device.setdefault((card_id, device_id), {"values": [], "approved_count": 0, "declined_count": 0, "last_approved_at": None})
                item["values"].append(amount)
                item["approved_count"] += 1
                item["last_approved_at"] = row["timestamp"]
        elif row["status"] == "declined":
            for key, bucket in (
                ((card_id, merchant_id), card_merchant),
                ((card_id, category), card_category),
            ):
                item = bucket.setdefault(key, {"values": [], "approved_count": 0, "declined_count": 0, "last_approved_at": None})
                item["declined_count"] += 1
            if device_id:
                item = card_device.setdefault((card_id, device_id), {"values": [], "approved_count": 0, "declined_count": 0, "last_approved_at": None})
                item["declined_count"] += 1
        # Approved refunds are historical financial events, but they are not
        # purchases and therefore must not become familiarity or decline
        # evidence. Their original transaction remains available in the
        # detailed history layer for reconciliation.

        card_recent[card_id].append({
            "authorization_id": row["authorization_id"],
            "timestamp": row["timestamp"],
            "merchant_id": merchant_id,
            "merchant_category": category,
            "device_id": device_id or None,
            "initiator_type": row["initiator_type"],
            "status": row["status"],
            "billing_amount_chf": _chf(amount),
        })

    def materialize(bucket: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for (left, right), item in bucket.items():
            result[f"{left}|{right}"] = _summary(
                item["values"], item["approved_count"], item["declined_count"], item["last_approved_at"]
            )
        return result

    return {
        "metadata": {
            "projection_version": "precomputed-kg-v1",
            "source": "authorization_history.csv",
            "record_count": len(history),
            "built_at": datetime.now(timezone.utc).isoformat(),
            "approved_purchase_only_for_baselines": True,
        },
        "customers": {
            customer_id: {
                "home_region": row["home_region"],
                "budget_style": row["budget_style"],
            }
            for customer_id, row in customers.items()
        },
        "accounts": {
            account_id: {
                "customer_id": row["customer_id"],
                "account_type": row["account_type"],
                "account_purpose": row["account_purpose"],
                "base_currency": row["base_currency"],
                "status": row["status"],
                "per_transaction_limit_chf": float(row["per_transaction_limit_chf"]),
                "monthly_limit_chf": float(row["monthly_limit_chf"]),
            }
            for account_id, row in accounts.items()
        },
        "cards": {
            card_id: {
                "account_id": row["account_id"],
                "card_type": row["card_type"],
                "card_purpose": row["card_purpose"],
                "status": row["status"],
                "online_enabled": row["online_enabled"] == "true",
                "international_enabled": row["international_enabled"] == "true",
                "virtual_card": row["virtual_card"] == "true",
            }
            for card_id, row in cards.items()
        },
        "merchants": {
            merchant_id: {key: row[key] for key in ("merchant_name", "merchant_category", "merchant_mcc", "merchant_country", "merchant_city")}
            for merchant_id, row in merchants.items()
        },
        "card_merchants": materialize(card_merchant),
        "card_devices": materialize(card_device),
        "card_categories": materialize(card_category),
        "device_cards": {device: sorted(card_ids) for device, card_ids in device_cards.items()},
        "card_amounts_chf": {card: [_chf(value) for value in values] for card, values in card_amounts.items()},
        "recent_activity": {card: values[-50:] for card, values in card_recent.items()},
    }


def to_node_link_graph(projection: dict[str, Any]) -> dict[str, Any]:
    """Convert the lookup projection into explicit typed nodes and edges.

    This representation is portable: a UI can render it directly and a graph
    database loader can map ``label`` to node labels and ``type`` to
    relationship types without reconstructing keys.
    """
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []

    def add_node(label: str, entity_id: str, properties: dict[str, Any]) -> None:
        nodes.append({
            "id": f"{label}:{entity_id}",
            "label": label,
            "key": entity_id,
            "properties": properties,
        })

    def add_relationship(rel_type: str, source: str, target: str,
                         properties: dict[str, Any] | None = None) -> None:
        relationships.append({
            "id": f"{rel_type}:{source}->{target}",
            "type": rel_type,
            "source": source,
            "target": target,
            "properties": properties or {},
        })

    for customer_id, properties in projection["customers"].items():
        add_node("Customer", customer_id, properties)

    for account_id, properties in projection["accounts"].items():
        customer_id = properties["customer_id"]
        add_node("Account", account_id, properties)
        add_relationship("OWNS", f"Customer:{customer_id}", f"Account:{account_id}")

    for card_id, properties in projection["cards"].items():
        account_id = properties["account_id"]
        add_node("Card", card_id, properties)
        add_relationship("HAS_CARD", f"Account:{account_id}", f"Card:{card_id}")

    categories = {merchant["merchant_category"] for merchant in projection["merchants"].values()}
    categories.update(key.split("|", 1)[1] for key in projection["card_categories"])
    for category in sorted(categories):
        add_node("Category", category, {"name": category})

    for merchant_id, properties in projection["merchants"].items():
        add_node("Merchant", merchant_id, properties)
        add_relationship(
            "IN_CATEGORY",
            f"Merchant:{merchant_id}",
            f"Category:{properties['merchant_category']}",
        )

    device_ids = set(projection["device_cards"])
    device_ids.update(key.split("|", 1)[1] for key in projection["card_devices"])
    for device_id in sorted(device_ids):
        add_node(
            "Device",
            device_id,
            {"observed_card_count": len(projection["device_cards"].get(device_id, []))},
        )

    for key, properties in projection["card_merchants"].items():
        card_id, merchant_id = key.split("|", 1)
        add_relationship(
            "USED_MERCHANT",
            f"Card:{card_id}",
            f"Merchant:{merchant_id}",
            properties,
        )

    for key, properties in projection["card_devices"].items():
        card_id, device_id = key.split("|", 1)
        add_relationship(
            "USED_DEVICE",
            f"Card:{card_id}",
            f"Device:{device_id}",
            properties,
        )

    for key, properties in projection["card_categories"].items():
        card_id, category = key.split("|", 1)
        add_relationship(
            "PURCHASED_CATEGORY",
            f"Card:{card_id}",
            f"Category:{category}",
            properties,
        )

    return {
        "metadata": {
            **projection["metadata"],
            "representation": "node-link",
            "node_count": len(nodes),
            "relationship_count": len(relationships),
        },
        "nodes": nodes,
        "relationships": relationships,
    }


def lookup_context(projection: dict[str, Any], *, card_id: str, merchant_id: str, device_id: str | None,
                   merchant_category: str | None, billing_amount_chf: float,
                   timestamp: str | None = None, recent_attempt_count_10m: int | None = None) -> dict[str, Any]:
    """Return explainable graph evidence for one live authorization."""
    merchant_key = f"{card_id}|{merchant_id}"
    merchant = projection["card_merchants"].get(merchant_key, {})
    device_key = f"{card_id}|{device_id}" if device_id else None
    device = projection["card_devices"].get(device_key, {}) if device_key else {}
    category_key = f"{card_id}|{merchant_category}" if merchant_category else None
    category = projection["card_categories"].get(category_key, {}) if category_key else {}
    amount_values = projection["card_amounts_chf"].get(card_id, [])
    amount_percentile = _percentile([round(value * 100) for value in amount_values], round(billing_amount_chf * 100))
    shared_cards = projection["device_cards"].get(device_id or "", [])

    evidence = {
        "merchant": {
            "relationship": "previously_used" if merchant.get("approved_count", 0) else "not_previously_approved",
            **merchant,
        },
        "device": {
            "relationship": "previously_used" if device.get("approved_count", 0) else "not_previously_approved",
            "shared_by_card_count": len(shared_cards),
            **device,
        },
        "category": {
            "relationship": "previously_purchased" if category.get("approved_count", 0) else "not_previously_purchased",
            **category,
        },
        "amount": {
            "billing_amount_chf": round(billing_amount_chf, 2),
            "card_approved_amount_percentile": amount_percentile,
            "card_history_count": len(amount_values),
        },
        "velocity": {
            "recent_attempt_count_10m": recent_attempt_count_10m,
            "elevated": recent_attempt_count_10m is not None and recent_attempt_count_10m >= 3,
        },
        "provenance": {
            "projection_version": projection["metadata"]["projection_version"],
            "as_of": timestamp or projection["metadata"]["built_at"],
        },
    }
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build"))
    parser.add_argument("--lookup", nargs=3, metavar=("CARD_ID", "MERCHANT_ID", "DEVICE_ID"))
    args = parser.parse_args()
    projection = build_projection(args.data_dir)
    args.output.mkdir(parents=True, exist_ok=True)
    output_file = args.output / "precomputed_knowledge_graph.json"
    output_file.write_text(json.dumps(projection, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {output_file} ({projection['metadata']['record_count']} history rows)")
    graph = to_node_link_graph(projection)
    graph_file = args.output / "precomputed_graph_node_link.json"
    graph_file.write_text(json.dumps(graph, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"wrote {graph_file} "
        f"({graph['metadata']['node_count']} nodes, "
        f"{graph['metadata']['relationship_count']} relationships)"
    )
    if args.lookup:
        card_id, merchant_id, device_id = args.lookup
        print(json.dumps(lookup_context(projection, card_id=card_id, merchant_id=merchant_id,
                                        device_id=device_id, merchant_category=None,
                                        billing_amount_chf=0.0), indent=2))


if __name__ == "__main__":
    main()
