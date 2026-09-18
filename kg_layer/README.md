# KG layer — Neo4j

Basic, standalone container for the AI/knowledge-graph layer. Not wired up
to any application code yet — just the data store running so the
schema/connection work can start.

- **Neo4j** (`neo4j:5-community`) — the knowledge graph store, with the
  browser UI and Bolt protocol exposed.

## Start it

```bash
cd kg_layer
docker compose up -d
```

## Connect

| | Neo4j |
| --- | --- |
| Host | `localhost` |
| Port | `7687` (bolt), `7474` (browser) |
| Auth | `neo4j` / `kg_layer_dev` |

Neo4j Browser: http://localhost:7474

This is a local dev default only — not meant for anything beyond this
container.
