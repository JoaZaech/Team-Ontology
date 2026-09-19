"""Technology-neutral source graph: one source node per CSV record."""
from ..common import digest

TYPES = {"customers": "Customer", "accounts": "Account", "cards": "Card", "merchants": "Merchant", "items": "Item", "authorization_history": "Authorization", "purchase_attempts": "PurchaseAttempt", "purchase_attempt_items": "PurchaseLine", "scenario_catalogue": "Scenario", "scenario_authorities": "Authority", "fx_rates": "FXRate"}


def build_knowledge(dataset):
    tables = dataset["tables"]
    nodes, edges = {}, {}
    def node(kind, key, properties, provenance):
        nid = f"{kind}:{key}"
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": kind, "properties": properties, "provenance": [provenance]}
        return nid
    def edge(source, relation, target, row, fields):
        provenance = dict(row["_source"], source_fields=fields)
        eid = f"{relation}:{source}->{target}:{row['_source']['source_id']}"
        edges[eid] = {"id": eid, "type": relation, "source": source, "target": target, "provenance": [provenance]}
    for table, rows in tables.items():
        for row in rows:
            node(TYPES[table], row["_source"]["source_id"], {k: v for k, v in row.items() if k != "_source"}, row["_source"])
    for table, rows in tables.items():
        for row in rows:
            nid = f"{TYPES[table]}:{row['_source']['source_id']}"
            def link(field, kind, relation):
                if row.get(field) is not None:
                    edge(nid, relation, f"{kind}:{row[field]}", row, [field])
            if table == "accounts":
                edge(f"Customer:{row['customer_id']}", "OWNS", nid, row, ["customer_id", "account_id"])
            if table == "cards":
                edge(f"Account:{row['account_id']}", "HAS_CARD", nid, row, ["account_id", "card_id"])
            if table in ("authorization_history", "purchase_attempts"):
                link("card_id", "Card", "ON_CARD")
                link("merchant_id", "Merchant", "AT_MERCHANT")
                if row.get("customer_device_id"):
                    device = node("Device", row["customer_device_id"], {}, row["_source"])
                    edge(nid, "USED_DEVICE", device, row, ["customer_device_id"])
                currency = node("Currency", row["currency"], {}, row["_source"])
                edge(nid, "IN_CURRENCY", currency, row, ["currency"])
            if table == "authorization_history":
                link("account_id", "Account", "ON_ACCOUNT")
                link("customer_id", "Customer", "BY_CUSTOMER")
                link("related_transaction_id", "Authorization", "REFUNDS" if row["transaction_type"] == "refund" else "RELATED_TO")
            if table == "purchase_attempts":
                link("authority_id", "Authority", "CONTROLLED_BY")
                link("related_authorization_id", "PurchaseAttempt", "RELATED_TO")
                edge(f"Scenario:{row['scenario_id']}", "HAS_ATTEMPT", nid, row, ["scenario_id", "authorization_id"])
                edge(f"Scenario:{row['scenario_id']}", "USES_AUTHORITY", f"Authority:{row['authority_id']}", row, ["scenario_id", "authority_id"])
            if table == "scenario_authorities":
                link("customer_id", "Customer", "FOR_CUSTOMER")
                link("card_id", "Card", "CONTROLS")
            if table == "purchase_attempt_items":
                edge(f"PurchaseAttempt:{row['authorization_id']}", "HAS_LINE", nid, row, ["authorization_id", "line_no"])
                link("item_id", "Item", "CONTAINS")
            if table in ("merchants", "items"):
                field, kind = ("merchant_category", "MerchantCategory") if table == "merchants" else ("item_category", "ItemCategory")
                category = node(kind, row[field], {}, row["_source"])
                edge(nid, "IN_CATEGORY", category, row, [field])
            if table == "fx_rates":
                src = node("Currency", row["from_currency"], {}, row["_source"])
                dst = node("Currency", row["to_currency"], {}, row["_source"])
                edge(src, "CONVERTED_BY", nid, row, ["from_currency", "rate", "rate_date"])
                edge(nid, "TO_CURRENCY", dst, row, ["to_currency"])
    graph = {"version": "kg-v1", "nodes": sorted(nodes.values(), key=lambda n: n["id"]), "relationships": sorted(edges.values(), key=lambda e: e["id"])}
    graph["snapshot_id"] = digest(graph)
    return graph


def validate_graph(graph, dataset):
    ids = [n["id"] for n in graph["nodes"]]
    id_set = set(ids)
    edge_ids = [e["id"] for e in graph["relationships"]]
    expected = {(r["_source"]["source_file"], r["_source"]["source_id"]) for rows in dataset["tables"].values() for r in rows}
    represented = {(p["source_file"], p["source_id"]) for n in graph["nodes"] for p in n["provenance"]}
    dangling = [e["id"] for e in graph["relationships"] if e["source"] not in id_set or e["target"] not in id_set]
    invalid_provenance = [e["id"] for e in graph["relationships"] if not e["provenance"] or any((p["source_file"], p["source_id"]) not in expected for p in e["provenance"])]
    report = {"node_count": len(ids), "relationship_count": len(edge_ids), "source_row_count": len(expected), "represented_source_rows": len(expected & represented), "duplicate_node_ids": len(ids) - len(set(ids)), "duplicate_relationship_ids": len(edge_ids) - len(set(edge_ids)), "dangling_relationships": dangling, "invalid_provenance": invalid_provenance, "unrepresented_rows": sorted(expected - represented)}
    report["valid"] = not any(report[k] for k in ("duplicate_node_ids", "duplicate_relationship_ids", "dangling_relationships", "invalid_provenance", "unrepresented_rows"))
    return report
