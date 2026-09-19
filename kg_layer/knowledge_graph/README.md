# Historical CSV precompute

Standalone JSON projection builder. For the current Neo4j container setup,
see [the KG layer README](../README.md).

## Rebuild the precomputed knowledge graph

`precompute.py` is a dependency-free batch builder for the online knowledge
projection. It reads only the historical CSVs and writes two rebuildable JSON
artifacts:

- `precomputed_knowledge_graph.json` is the compact lookup representation with
  card–merchant, card–device, card–category, device-sharing, amount-baseline
  and recent-activity summaries.
- `precomputed_graph_node_link.json` is a portable graph representation with
  explicit typed `nodes` and `relationships`. It can be rendered by a graph UI
  or mapped directly into Neo4j.

```bash
cd kg_layer/knowledge_graph
python3 precompute.py \
  --data-dir ../../viseca-2026/data \
  --output build
```

The output is evidence, not a decision. A lookup returns facts such as
`previously_used`, approved counts, amount percentile and device sharing. The
existing `guardian.py` remains responsible for `approve`, `step_up` or
`decline`. Approved purchases only are used for familiarity and amount
baselines; declined attempts remain available as separate evidence.

The projection can be inspected without starting Neo4j:

```python
from precompute import build_projection, lookup_context

projection = build_projection("../../viseca-2026/data")
context = lookup_context(
    projection,
    card_id="CA0001",
    merchant_id="ME0001",
    device_id="DVC-13A598",
    merchant_category="groceries",
    billing_amount_chf=20.0,
    recent_attempt_count_10m=0,
)
```

For production, persist the JSON projection in object storage or load its
summaries into Redis/Neo4j. Keep the source CSVs and projection version in the
decision evidence so the result can be reproduced.

The node-link graph contains these relationship types:

```text
(Customer)-[:OWNS]->(Account)
(Account)-[:HAS_CARD]->(Card)
(Merchant)-[:IN_CATEGORY]->(Category)
(Card)-[:USED_MERCHANT {summary...}]->(Merchant)
(Card)-[:USED_DEVICE {summary...}]->(Device)
(Card)-[:PURCHASED_CATEGORY {summary...}]->(Category)
```

Summary relationship properties include approved and declined counts,
approved CHF total, average, p95 and last-approved timestamp.

