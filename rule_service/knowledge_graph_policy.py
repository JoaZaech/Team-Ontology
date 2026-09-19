"""Create persisted wallet-policy documents from trusted knowledge-graph evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any


KG_ROOT = Path(__file__).resolve().parents[1] / "Knowledge_graph"
if str(KG_ROOT) not in sys.path:
    sys.path.insert(0, str(KG_ROOT))

from kg_rootcause.ingestion import load_dataset
from kg_rootcause.precompute import EvidenceIndex


SPEND_CATEGORIES = {
    "Groceries": frozenset({"groceries"}),
    "Transport": frozenset({"transport", "fuel"}),
    "Dining": frozenset({"dining", "food_delivery"}),
    "Shopping": frozenset({"books", "clothing", "cosmetics", "electronics", "gift_card", "health", "home_improvement", "household", "sporting_goods"}),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _chf(cents: int) -> float:
    return float(Decimal(cents) / Decimal(100))


def build_wallet_policy_from_knowledge_graph(
    data_dir: Path,
    card_id: str | None = None,
    policy_id: str | None = None,
) -> dict[str, Any]:
    dataset, _ = load_dataset(data_dir)
    index = EvidenceIndex(dataset)
    selected_card_id = card_id or min(index.by_card)
    card = dataset["indexes"]["cards"].get(selected_card_id)
    if card is None:
        raise ValueError("cardId is not present in the knowledge graph")
    customer_id = dataset["indexes"]["accounts"][card["account_id"]]["customer_id"]
    purchases = [
        row for row in index.by_card[selected_card_id]
        if row["status"] == "approved" and row["transaction_type"] == "purchase"
    ]
    if not purchases:
        raise ValueError("knowledge graph has no approved purchase evidence for this card")

    profiles: dict[str, dict[str, Any]] = {}
    category_evidence: dict[str, list[str]] = {}
    for category, dataset_categories in SPEND_CATEGORIES.items():
        category_rows = [row for row in purchases if row["merchant_category"] in dataset_categories]
        if not category_rows:
            raise ValueError(f"knowledge graph has no {category.lower()} evidence for this card")
        amounts = [row["billing_amount_chf"] for row in category_rows]
        lower, upper = min(amounts), max(amounts)
        profiles[category] = {
            "maximumChf": _chf(upper),
            "typicalRange": f"CHF {_chf(lower):.2f}-{_chf(upper):.2f}",
            "explanation": f"Derived from {len(category_rows)} approved {category.lower()} purchases in the knowledge graph.",
        }
        category_evidence[category] = [row["authorization_id"] for row in category_rows]

    daily_spend = defaultdict(int)
    for row in purchases:
        daily_spend[row["timestamp"][:10]] += row["billing_amount_chf"]
    daily_limit_cents = max(daily_spend.values())
    evidence_ids = [row["authorization_id"] for row in purchases]
    as_of = max(row["timestamp"] for row in purchases)
    created_at = _now()
    return {
        "policyId": policy_id or f"wallet-policy_{selected_card_id}_default",
        "schemaVersion": "2026-09-01",
        "revision": 1,
        "subject": {"customerId": customer_id, "cardId": selected_card_id},
        "enabled": True,
        "dailySpendingLimitChf": _chf(daily_limit_cents),
        "adaptiveSpendProfiles": profiles,
        "reviewTriggers": ["new_merchant"],
        "assistantAuthority": "trusted",
        "effectiveFrom": created_at,
        "updatedAt": created_at,
        "updatedBy": "knowledge-graph",
        "knowledgeGraph": {
            "graphVersion": "kg-v1",
            "calculationVersion": "wallet-policy-derivation-v1",
            "asOf": as_of,
            "evidenceIds": evidence_ids,
            "categoryEvidence": category_evidence,
        },
    }