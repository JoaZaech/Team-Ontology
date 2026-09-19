from ..schema import validate


def get_transaction_context(transaction, snapshot, dataset, index, runtime_events=(), policy=None):
    t = transaction
    ids = dataset["indexes"]
    card = ids["cards"][t["card_id"]]
    account = ids["accounts"][card["account_id"]]
    customer = ids["customers"][account["customer_id"]]
    merchant = ids["merchants"][t["merchant_id"]]
    authority = ids["scenario_authorities"][t["authority_id"]]
    items = [r for r in dataset["tables"]["purchase_attempt_items"] if r["authorization_id"] == t["authorization_id"]]
    evidence = index.get_context(t["card_id"], t["merchant_id"], t["customer_device_id"], t["timestamp"], runtime_events)
    nid = "NewTransaction:" + t["authorization_id"]
    node = {"id": nid, "type": "NewTransaction", "properties": {k: v for k, v in t.items() if k != "_source"}, "provenance": [t["_source"]]}
    links = [("SOURCE_RECORD", "PurchaseAttempt:" + t["authorization_id"]), ("ON_CARD", "Card:" + t["card_id"]), ("AT_MERCHANT", "Merchant:" + t["merchant_id"]), ("CONTROLLED_BY", "Authority:" + t["authority_id"]), ("IN_SCENARIO", "Scenario:" + t["scenario_id"])]
    if t["customer_device_id"]:
        links.append(("USED_DEVICE", "Device:" + t["customer_device_id"]))
    links += [("HAS_LINE", "PurchaseLine:" + r["_source"]["source_id"]) for r in items]
    edges = [{"id": f"CURRENT_{kind}:{nid}->{target}", "type": kind, "source": nid, "target": target, "provenance": [t["_source"]]} for kind, target in links]
    missing = []
    if not items:
        missing.append("basket")
    if t["customer_device_id"] is None and t["channel"] in ("ecommerce", "recurring"):
        missing.append("device")
    if not evidence["amount_profile"]["approved_count"]:
        missing.append("approved_purchase_history")
    if evidence["amount_profile"]["approved_count"] < 5:
        missing.append("sufficient_amount_history")
    semantics = {"merchant_category": merchant["merchant_category"], "item_categories": sorted({r["item_category"] for r in items}), "familiar_merchant": evidence["card_merchant"]["approved_count"] > 0, "familiar_device": evidence["card_device"]["approved_count"] > 0, "order_returnable": t["order_returnable"], "order_cancellable": t["order_cancellable"]}
    if policy:
        semantics["item_category_matches"] = bool(items) and all(r["item_category"] in policy["item_categories"] for r in items)
        semantics["delivery_matches"] = t["fulfillment_method"] == policy["fulfillment_method"]
    return validate("KGContext", {"authorization_id": t["authorization_id"], "as_of": t["timestamp"], "snapshot_id": snapshot["snapshot_id"], "entities": {"card": card, "account": account, "customer": customer, "merchant": merchant, "authority": authority, "items": items}, "historical_evidence": evidence, "semantic_matches": semantics, "missing_evidence": missing, "overlay": {"nodes": [node], "relationships": edges}, "versions": {"graph": "kg-v1", "ontology": "ontology-v1", "evidence": "evidence-v1"}})
