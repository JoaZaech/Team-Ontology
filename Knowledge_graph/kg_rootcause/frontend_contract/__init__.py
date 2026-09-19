"""Reference/path integrity checks independent of schema shape validation."""

def audit_explanation(explanation, snapshot, overlay, dataset):
    nodes = {n["id"]: n for n in snapshot["nodes"] + overlay["nodes"]}
    edges = {e["id"]: e for e in snapshot["relationships"] + overlay["relationships"]}
    source_rows = {(r["_source"]["source_file"], r["_source"]["source_id"]): r for rows in dataset["tables"].values() for r in rows}
    source_events = set(dataset["indexes"]["authorization_history"]) | set(dataset["indexes"]["purchase_attempts"])
    errors, valid_paths = [], 0
    for path in explanation["root_cause_paths"]:
        valid = len(path["relationships"]) == len(path["nodes"]) - 1
        valid &= all(n in nodes for n in path["nodes"])
        valid &= all(e in edges for e in path["relationships"])
        valid &= all(e in source_events for e in path["source_event_ids"])
        if valid:
            for a, b, eid in zip(path["nodes"], path["nodes"][1:], path["relationships"]):
                edge = edges[eid]
                valid &= {a, b} == {edge["source"], edge["target"]}
                valid &= bool(edge["provenance"]) and all((p["source_file"], p["source_id"]) in source_rows and set(p["source_fields"]) <= set(source_rows[(p["source_file"], p["source_id"])]) for p in edge["provenance"])
        if valid:
            valid_paths += 1
        else:
            errors.append(path["path_id"])
    hnodes = {n["id"] for n in explanation["highlight_graph"]["nodes"]}
    hedges = {e["id"] for e in explanation["highlight_graph"]["relationships"]}
    for n in explanation["highlight_graph"]["nodes"]:
        if n["id"] not in nodes or n != nodes[n["id"]]:
            errors.append(n["id"])
    for e in explanation["highlight_graph"]["relationships"]:
        if e["id"] not in edges or e != edges[e["id"]] or e["source"] not in hnodes or e["target"] not in hnodes:
            errors.append(e["id"])
    for h in explanation["highlights"]:
        if h["graph_id"] not in hnodes | hedges:
            errors.append(h["graph_id"])
    for path in explanation["root_cause_paths"]:
        if not set(path["nodes"]) <= hnodes or not set(path["relationships"]) <= hedges:
            errors.append(path["path_id"])
    return {"errors": errors, "valid_paths": valid_paths, "path_count": len(explanation["root_cause_paths"])}
