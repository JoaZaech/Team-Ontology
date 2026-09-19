"""Persistent offline storage for the knowledge graph."""

__all__ = ["GraphStore", "persist_graph_store"]


def __getattr__(name):
	if name in __all__:
		from .sqlite_graph import GraphStore, persist_graph_store

		return {"GraphStore": GraphStore, "persist_graph_store": persist_graph_store}[name]
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")