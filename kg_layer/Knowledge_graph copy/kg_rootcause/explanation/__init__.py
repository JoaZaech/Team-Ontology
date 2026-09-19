"""Decisions follow hard-rule precedence; paths contain real source graph edges."""
from collections import deque
from ..schema import validate


def explain_decision(transaction, policy, checks, context, snapshot):
    validate("GuardrailCheckInput", {"transaction": transaction, "confirmed_policy": policy, "checks": checks, "context": context})
    if not checks:
        raise ValueError("An explanation requires guardrail checks")
    hard = [c for c in checks if c["kind"] == "hard" and c["status"] == "fail"]
    uncertain = [c for c in checks if c["status"] == "unknown" or (c["kind"] == "uncertainty" and c["status"] == "fail")]
    active = hard or uncertain or checks
    decision = "decline" if hard else "step_up" if uncertain else "approve"
    nodes = {n["id"]: n for n in snapshot["nodes"] + context["overlay"]["nodes"]}
    edges = {e["id"]: e for e in snapshot["relationships"] + context["overlay"]["relationships"]}
    adjacency = {}
    for e in edges.values():
        for a, b in [(e["source"], e["target"]), (e["target"], e["source"])]:
            adjacency.setdefault(a, []).append((b, e["id"]))
    start = "NewTransaction:" + transaction["authorization_id"]
    # BFS only through this transaction, shared identities and prior support events.
    # Never traverse other scenario attempts to manufacture a shorter explanation.
    supported = {eid for c in checks for eid in c["source_event_ids"]}
    allowed = {start, "PurchaseAttempt:" + transaction["authorization_id"]}
    allowed.update("Authorization:" + eid if eid.startswith("TR") else "PurchaseAttempt:" + eid for eid in supported)
    allowed.update(nid for nid in nodes if nodes[nid]["type"] in {"Card", "Merchant", "Item", "ItemCategory", "MerchantCategory", "Authority", "Customer", "Account", "Device"})
    allowed.update("PurchaseLine:" + r["_source"]["source_id"] for r in context["entities"]["items"])
    previous = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for nxt, eid in sorted(adjacency.get(current, [])):
            if nxt in allowed and nxt not in previous:
                previous[nxt] = (current, eid)
                queue.append(nxt)
    def path_to(target):
        if target not in previous:
            raise ValueError(f"No provenance path to {target}")
        path_nodes, path_edges = [target], []
        while previous[path_nodes[-1]] is not None:
            parent, eid = previous[path_nodes[-1]]
            path_nodes.append(parent)
            path_edges.append(eid)
        return list(reversed(path_nodes)), list(reversed(path_edges))
    supporting, counter, paths, highlights = [], [], [], []
    selected_nodes, selected_edges = {start}, set()
    weight_units = 10000 // len(active)
    for number, check in enumerate(checks):
        is_active = check in active
        position = active.index(check) if is_active else -1
        weight = (weight_units if position < len(active)-1 else 10000-weight_units*(len(active)-1))/100 if is_active else 0
        evidence = {"reason_code": check["rule"], "status": check["status"], "expected": check["expected"], "observed": check["observed"], "source_event_ids": check["source_event_ids"], "evidence_contribution_percent": weight}
        (supporting if is_active or check["status"] != "pass" else counter).append(evidence)
        targets = ["PurchaseAttempt:" + transaction["authorization_id"]]
        if check["rule"] == "item_category":
            targets += ["Item:" + r["item_id"] for r in context["entities"]["items"]]
        if check["rule"] == "authority_active":
            targets += ["Authority:" + transaction["authority_id"]]
        targets += [("Authorization:" if eid.startswith("TR") else "PurchaseAttempt:") + eid for eid in check["source_event_ids"]]
        for j, target in enumerate(targets):
            pnodes, pedges = path_to(target)
            selected_nodes.update(pnodes)
            selected_edges.update(pedges)
            paths.append({"path_id": f"{transaction['authorization_id']}:{number}:{j}", "reason_code": check["rule"], "nodes": pnodes, "relationships": pedges, "source_event_ids": [target.split(":", 1)[1]] if target.startswith(("Authorization:", "PurchaseAttempt:")) else [], "contribution_percent": weight})
            for gid in pnodes + pedges:
                highlights.append({"graph_id": gid, "reason_code": check["rule"], "highlight_level": "direct" if hard and is_active else "supporting" if is_active else "counter", "highlight_score": weight/100, "contribution_percent": weight, "source_event_ids": check["source_event_ids"]})
    result = {"authorization_id": transaction["authorization_id"], "decision": decision, "decision_cause": {"type": "hard_rule" if hard else "uncertainty" if uncertain else "all_checks_pass", "rules": [c["rule"] for c in active], "decision_contribution_percent": 100}, "supporting_evidence": supporting, "counter_evidence": counter, "root_cause_paths": paths, "supporting_event_ids": sorted(supported), "highlight_graph": {"nodes": [nodes[n] for n in sorted(selected_nodes)], "relationships": [edges[e] for e in sorted(selected_edges)]}, "highlights": highlights, "contribution_label": "explanation contributions; not proven fraud causes", "versions": {"graph": "kg-v1", "semantic_ontology": "ontology-v1", "policy": policy["version"], "evidence_weights": "equal-explanation-weights-v1", "model": None}}
    return validate("KG_Rootcause", result)
