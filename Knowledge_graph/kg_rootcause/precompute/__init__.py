"""Card-indexed histories with exclusive event-time queries and auditable aggregates."""
from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta
import math
from ..common import timestamp


def summary(rows, as_of):
    purchases = [r for r in rows if r["status"] == "approved" and r["transaction_type"] == "purchase"]
    amounts = sorted(r["billing_amount_chf"] for r in purchases)
    return {"status": "known" if purchases else ("known_but_unapproved" if rows else "no_prior_relationship"), "approved_count": len(purchases), "declined_count": sum(r["status"] == "declined" for r in rows), "approved_purchase_cents": sum(amounts), "net_approved_cents": sum(r["billing_amount_chf"] for r in rows if r["status"] == "approved"), "amount_p50_cents": amounts[math.ceil(len(amounts) * .5)-1] if amounts else None, "amount_p95_cents": amounts[math.ceil(len(amounts) * .95)-1] if amounts else None, "first_approved_at": purchases[0]["timestamp"] if purchases else None, "last_approved_at": purchases[-1]["timestamp"] if purchases else None, "supporting_event_ids": [r["authorization_id"] for r in rows], "as_of": as_of, "calculation_version": "evidence-v1"}


class EvidenceIndex:
    def __init__(self, dataset):
        self.dataset = dataset
        self.by_card = defaultdict(list)
        for row in dataset["tables"]["authorization_history"]:
            self.by_card[row["card_id"]].append(row)
        for rows in self.by_card.values():
            rows.sort(key=lambda r: (timestamp(r["timestamp"]), r["authorization_id"]))
        self.times = {card: [timestamp(r["timestamp"]) for r in rows] for card, rows in self.by_card.items()}

    def get_context(self, card_id, merchant_id, device_id, timestamp_value, runtime_events=()):
        cutoff = timestamp(timestamp_value)
        rows = list(self.by_card.get(card_id, [])[:bisect_left(self.times.get(card_id, []), cutoff)])
        rows += [r for r in runtime_events if r["card_id"] == card_id and timestamp(r["timestamp"]) < cutoff]
        rows.sort(key=lambda r: (timestamp(r["timestamp"]), r["authorization_id"]))
        merchant = self.dataset["indexes"]["merchants"][merchant_id]
        def select(field, value):
            return summary([r for r in rows if r.get(field) == value], timestamp_value)
        recent = [r for r in rows if cutoff - timedelta(minutes=10) <= timestamp(r["timestamp"])]
        card = self.dataset["indexes"]["cards"][card_id]
        customer = self.dataset["indexes"]["accounts"][card["account_id"]]["customer_id"]
        customer_rows = []
        for cid, history in self.by_card.items():
            c = self.dataset["indexes"]["cards"][cid]
            if self.dataset["indexes"]["accounts"][c["account_id"]]["customer_id"] == customer:
                customer_rows.extend(history[:bisect_left(self.times[cid], cutoff)])
        customer_rows += [r for r in runtime_events if r["customer_id"] == customer and timestamp(r["timestamp"]) < cutoff]
        customer_rows.sort(key=lambda r: (timestamp(r["timestamp"]), r["authorization_id"]))
        device = select("customer_device_id", device_id) if device_id else dict(summary([], timestamp_value), status="not_applicable")
        return {"card_merchant": select("merchant_id", merchant_id), "card_device": device, "card_category": select("merchant_category", merchant["merchant_category"]), "card_country": select("merchant_country", merchant["merchant_country"]), "customer_device": summary([r for r in customer_rows if device_id and r["customer_device_id"] == device_id], timestamp_value), "amount_profile": summary(rows, timestamp_value), "time_of_day": {str(hour): summary([r for r in rows if timestamp(r["timestamp"]).hour == hour], timestamp_value) for hour in sorted({timestamp(r["timestamp"]).hour for r in rows})}, "initiator_activity": {kind: select("initiator_type", kind) for kind in ("human", "agent", "merchant")}, "recent_attempts": summary(recent, timestamp_value), "duplicate_candidates": [r["authorization_id"] for r in recent if r["merchant_id"] == merchant_id and r["status"] == "approved"], "retry_candidates": [r["authorization_id"] for r in recent if r["merchant_id"] == merchant_id and r["status"] == "declined"]}


def precompute_summaries(dataset):
    """Materialize end-of-history summaries; earlier queries still use the temporal index."""
    rows = dataset["tables"]["authorization_history"]
    as_of = (max(timestamp(r["timestamp"]) for r in rows) + timedelta(microseconds=1)).isoformat()
    dimensions = {"card_merchant": ("card_id", "merchant_id"), "card_device": ("card_id", "customer_device_id"), "card_category": ("card_id", "merchant_category"), "card_country": ("card_id", "merchant_country"), "customer_device": ("customer_id", "customer_device_id"), "card_amount": ("card_id",), "initiator_activity": ("card_id", "initiator_type")}
    output = {}
    for name, fields in dimensions.items():
        groups = defaultdict(list)
        for row in rows:
            key = tuple(row[f] for f in fields)
            if all(v is not None for v in key):
                groups[key].append(row)
        output[name] = [{"key": dict(zip(fields, key)), **summary(sorted(group, key=lambda r: (timestamp(r["timestamp"]), r["authorization_id"])), as_of)} for key, group in sorted(groups.items())]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["card_id"], timestamp(row["timestamp"]).hour)].append(row)
    output["time_of_day"] = [{"key": {"card_id": key[0], "hour_utc": key[1]}, **summary(sorted(group, key=lambda r: (timestamp(r["timestamp"]), r["authorization_id"])), as_of)} for key, group in sorted(groups.items())]
    return {"as_of": as_of, "calculation_version": "evidence-v1", "aggregates": output}
